"""Stream en tiempo real de pump.fun vía PumpPortal (wss://pumpportal.fun/api/data, gratis).

Mensajes:
  create: {signature, mint, traderPublicKey, txType:"create", initialBuy, solAmount, bondingCurveKey,
           vTokensInBondingCurve, vSolInBondingCurve, marketCapSol, name, symbol, uri, pool}
  trade:  {signature, mint, traderPublicKey, txType:"buy"|"sell", tokenAmount, solAmount, newTokenBalance,
           bondingCurveKey, vTokensInBondingCurve, vSolInBondingCurve, marketCapSol, pool}

Precio en SOL = vSolInBondingCurve / vTokensInBondingCurve (en la curva).
Para cada token nuevo se guarda la historia de trades de los primeros minutos; después se
deja de escuchar salvo que tengamos posición abierta.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger("live.stream")

WS_URL = "wss://pumpportal.fun/api/data"


@dataclass
class Trade:
    ts: float
    wallet: str
    side: str            # buy | sell
    sol: float
    tokens: float
    price: float         # SOL por token


@dataclass
class TokenState:
    mint: str
    symbol: str
    name: str
    creator: str
    created_ts: float
    base_price: float                  # precio de apertura de la curva
    pool: str = "pump"
    trades: list[Trade] = field(default_factory=list)
    last_price: float = 0.0
    last_ts: float = 0.0
    mcap_sol: float = 0.0
    evaluated: bool = False            # ya se evaluó al minuto 2
    decided: bool = False              # ya se decidió entrar/no entrar

    def price_at(self, ts: float) -> float:
        """Último precio operado hasta `ts` (sin mirar el futuro)."""
        px = self.base_price
        for t in self.trades:
            if t.ts > ts:
                break
            px = t.price
        return px

    def window(self, seconds: float) -> list[Trade]:
        lim = self.created_ts + seconds
        return [t for t in self.trades if t.ts <= lim]


def _price(msg: dict) -> float:
    try:
        vs = float(msg.get("vSolInBondingCurve") or 0)
        vt = float(msg.get("vTokensInBondingCurve") or 0)
        if vs > 0 and vt > 0:
            return vs / vt
    except (TypeError, ValueError):
        pass
    try:  # fuera de la curva: precio implícito del trade
        sol = float(msg.get("solAmount") or 0); tok = float(msg.get("tokenAmount") or 0)
        return sol / tok if sol > 0 and tok > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


class PumpStream(threading.Thread):
    """Hilo que mantiene la conexión, reconecta y alimenta `tokens`."""

    def __init__(self, keep_seconds: float = 300.0, max_tokens: int = 4000, watch_seconds: float = 150.0, sample: float = 1.0):
        """watch_seconds: cuánto se escuchan los trades de cada token nuevo (PumpPortal cobra 0,01 SOL por cada
        10.000 trades); después se desuscribe salvo que esté en `keep` (candidato) o `pinned` (posición).
        sample: fracción de los tokens nuevos a los que se les escuchan trades (1.0 = todos)."""
        super().__init__(daemon=True, name="pumpstream")
        self.watch_seconds = watch_seconds
        self.sample = sample
        self.keep: set[str] = set()            # candidatos: seguir escuchando hasta decidir
        self.trades_streamed = 0
        self.tokens: dict[str, TokenState] = {}
        self.keep_seconds = keep_seconds
        self.max_tokens = max_tokens
        self.pinned: set[str] = set()          # posiciones abiertas: se escuchan siempre
        self.lock = threading.Lock()
        self.ws = None
        self.connected = False
        self.msgs = 0
        self.last_msg_ts = 0.0
        self.creates = 0
        self.errors = deque(maxlen=20)
        self.counts: dict[str, int] = {}
        self.samples = deque(maxlen=5)          # últimos mensajes sin mint (acks, errores del servidor)
        self._pending_sub: list[str] = []
        self._last_sub = 0.0
        self._subscribed: set[str] = set()
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self.accounts: set[str] = set()                 # billeteras seguidas (subscribeAccountTrade)
        self.account_events: deque = deque(maxlen=5000)  # trades de billeteras seguidas, en orden
        self.account_trades = 0

    # ---------- API ----------
    def keep_watching(self, mint: str) -> None:
        with self.lock:
            self.keep.add(mint)
        self._subscribe([mint], now=True)

    def release(self, mint: str) -> None:
        with self.lock:
            self.keep.discard(mint)

    def follow_accounts(self, wallets: list[str]) -> None:
        new = [w for w in wallets if w not in self.accounts]
        with self.lock:
            self.accounts.update(new)
        if new:
            self._send({"method": "subscribeAccountTrade", "keys": new})

    def pin(self, mint: str, symbol: str = "", price: float = 0.0) -> None:
        with self.lock:
            self.pinned.add(mint)
            if mint not in self.tokens:   # token que no vimos nacer (modo seguidor): placeholder para seguir su precio
                self.tokens[mint] = TokenState(mint=mint, symbol=symbol, name="", creator="", created_ts=time.time() - 3600,
                                               base_price=price or 1e-9, last_price=price, last_ts=time.time() if price else 0.0)
        self._subscribe([mint], now=True)

    def unpin(self, mint: str) -> None:
        with self.lock:
            self.pinned.discard(mint)

    def snapshot(self, mint: str) -> TokenState | None:
        with self.lock:
            return self.tokens.get(mint)

    def young(self, min_age: float, max_age: float) -> list[TokenState]:
        now = time.time()
        with self.lock:
            return [t for t in self.tokens.values() if min_age <= now - t.created_ts <= max_age]

    def stop(self) -> None:
        self._stop.set()
        try:
            if self.ws:
                self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------- interno ----------
    def _send(self, payload: dict) -> None:
        try:
            if self.ws and self.connected:
                with self._send_lock:
                    self.ws.send(json.dumps(payload))
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"{time.strftime('%H:%M:%S')} send: {e}")

    def _subscribe(self, mints: list[str], now: bool = False) -> None:
        new = [m for m in mints if m not in self._subscribed and m not in self._pending_sub]
        self._pending_sub.extend(new)
        if self._pending_sub and (now or time.time() - self._last_sub >= 2.0):
            batch, self._pending_sub = self._pending_sub, []
            self._subscribed.update(batch)
            self._last_sub = time.time()
            self._send({"method": "subscribeTokenTrade", "keys": batch})

    def _unsubscribe(self, mints: list[str]) -> None:
        old = [m for m in mints if m in self._subscribed]
        if not old:
            return
        self._subscribed.difference_update(old)
        self._send({"method": "unsubscribeTokenTrade", "keys": old})

    def _on_message(self, raw: str) -> None:
        self.msgs += 1
        self.last_msg_ts = time.time()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict) or "mint" not in msg:
            self.samples.append(raw[:200]); self.counts["otros"] = self.counts.get("otros", 0) + 1
            if "funded with at least" in raw:
                # PumpPortal no reconoció la API key fondeada en esta conexión: reconectar (su chequeo es por conexión)
                self.counts["sin_fondos"] = self.counts.get("sin_fondos", 0) + 1
                if self.counts["sin_fondos"] % 20 == 1:
                    raise RuntimeError("PumpPortal: key no reconocida como fondeada; reconecto")
            return
        self.counts[str(msg.get("txType"))] = self.counts.get(str(msg.get("txType")), 0) + 1
        now = time.time()
        tx = msg.get("txType")
        mint = msg["mint"]
        if tx == "create":
            if (msg.get("pool") or "pump") != "pump":
                return
            px = _price(msg)
            # el create trae el estado DESPUÉS de la compra inicial del dev; precio base de la curva pump.fun
            base = 30.0 / 1_073_000_000.0
            if px <= 0:
                px = base
            st = TokenState(mint=mint, symbol=str(msg.get("symbol") or ""), name=str(msg.get("name") or ""),
                            creator=str(msg.get("traderPublicKey") or ""), created_ts=now, base_price=base,
                            pool=str(msg.get("pool") or "pump"), last_price=px, last_ts=now,
                            mcap_sol=float(msg.get("marketCapSol") or 0))
            init = float(msg.get("solAmount") or 0)
            if init > 0:
                st.trades.append(Trade(now, st.creator, "buy", init, float(msg.get("initialBuy") or 0), px))
            with self.lock:
                self.tokens[mint] = st
                self.creates += 1
            if self.sample >= 1.0 or (hash(mint) % 1000) < self.sample * 1000:
                self._subscribe([mint])
            else:
                st.decided = st.evaluated = True      # no muestreado: no se evalúa
            return
        if tx in ("buy", "sell") and msg.get("traderPublicKey") in self.accounts:
            self.account_trades += 1
            self.account_events.append({"ts": now, "wallet": msg.get("traderPublicKey"), "mint": mint, "side": tx,
                                        "sol": float(msg.get("solAmount") or 0), "tokens": float(msg.get("tokenAmount") or 0),
                                        "price": _price(msg), "pool": msg.get("pool"), "new_balance": float(msg.get("newTokenBalance") or 0),
                                        "mcap_sol": float(msg.get("marketCapSol") or 0), "sig": msg.get("signature")})
        if tx in ("buy", "sell"):
            with self.lock:
                st = self.tokens.get(mint)
            if not st:
                return
            px = _price(msg)
            t = Trade(now, str(msg.get("traderPublicKey") or ""), tx, float(msg.get("solAmount") or 0),
                      float(msg.get("tokenAmount") or 0), px if px > 0 else st.last_price)
            self.trades_streamed += 1
            with self.lock:
                st.trades.append(t)
                st.last_price, st.last_ts = t.price, now
                st.mcap_sol = float(msg.get("marketCapSol") or st.mcap_sol)

    def _gc(self) -> None:
        now = time.time()
        with self.lock:
            # dejar de escuchar trades de los tokens que ya pasaron la ventana de observación (ahorro de cuota)
            expired = [m for m, t in self.tokens.items()
                       if m in self._subscribed and m not in self.pinned and m not in self.keep and now - t.created_ts > self.watch_seconds]
            drop = [m for m, t in self.tokens.items()
                    if m not in self.pinned and now - t.created_ts > self.keep_seconds]
        self._unsubscribe(expired)
        with self.lock:
            if len(self.tokens) - len(drop) > self.max_tokens:
                extra = sorted((t.created_ts, m) for m, t in self.tokens.items() if m not in self.pinned and m not in drop)
                drop += [m for _, m in extra[: len(self.tokens) - len(drop) - self.max_tokens]]
            for m in drop:
                self.tokens.pop(m, None)
        self._unsubscribe(drop)

    def run(self) -> None:
        import websocket  # websocket-client

        backoff = 2
        while not self._stop.is_set():
            try:
                key = os.getenv("PUMPPORTAL_API_KEY", "").strip()
                url = f"{WS_URL}?api-key={key}" if key else WS_URL
                self.ws = websocket.create_connection(url, timeout=30)
                self.connected = True
                backoff = 2
                self._subscribed.clear(); self._pending_sub.clear()
                self._send({"method": "subscribeNewToken"})
                with self.lock:
                    pinned = list(self.pinned); accounts = list(self.accounts)
                if pinned:
                    self._subscribe(pinned, now=True)
                if accounts:
                    self._send({"method": "subscribeAccountTrade", "keys": accounts})
                log.info("stream conectado")
                last_gc = time.time()
                while not self._stop.is_set():
                    try:
                        raw = self.ws.recv()
                    except websocket.WebSocketTimeoutException:
                        if time.time() - self.last_msg_ts > 120:
                            raise RuntimeError("sin mensajes hace 120 s")
                        continue
                    if raw:
                        self._on_message(raw)
                    if self._pending_sub and time.time() - self._last_sub >= 2.0:
                        self._subscribe([])
                    if time.time() - last_gc > 15:
                        self._gc(); last_gc = time.time()
            except Exception as e:  # noqa: BLE001
                self.connected = False
                self.errors.append(f"{time.strftime('%H:%M:%S')} {e}")
                log.warning("stream caído: %s; reconecto en %ss", e, backoff)
                try:
                    if self.ws:
                        self.ws.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        self.connected = False
