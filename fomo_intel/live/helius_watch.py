"""Seguimiento de billeteras directamente en la cadena vía Helius (websocket estándar de Solana).

Por cada billetera seguida: logsSubscribe {mentions: [wallet]} -> cada transacción que la menciona llega
en 1-2 s con su firma. Un hilo aparte baja la transacción (getTransaction jsonParsed) y la convierte en
un evento compra/venta: qué token, cuántos SOL, cuántos tokens, precio. Independiente de PumpPortal.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import deque

import requests

log = logging.getLogger("live.helius")
SOL_MINT = "So11111111111111111111111111111111111111112"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def parse_create(tx: dict, wallet: str) -> dict | None:
    """Si la tx es un 'create' de pump.fun firmado por `wallet`, devuelve {mint, initial_sol, initial_tokens}."""
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return None
    logs = " ".join(meta.get("logMessages") or [])
    if "Instruction: Create" not in logs:
        return None
    msg = tx["transaction"]["message"]
    keys_full = msg["accountKeys"]
    # el mint es una cuenta nueva que FIRMA la creación junto con el creador
    signers = [k.get("pubkey") for k in keys_full if isinstance(k, dict) and k.get("signer")]
    cands = [k for k in signers if k != wallet]
    mint = next((k for k in cands if k.endswith("pump")), cands[0] if cands else None)
    if not mint:
        mints = [b.get("mint") for b in (meta.get("postTokenBalances") or []) if b.get("mint") != SOL_MINT]
        mint = next((m for m in mints if m.endswith("pump")), mints[0] if mints else None)
    if not mint:
        return None
    # compra inicial del creador (si hubo)
    tok = 0.0
    for b in meta.get("postTokenBalances") or []:
        if b.get("owner") == wallet and b.get("mint") == mint:
            tok += float(b["uiTokenAmount"].get("uiAmount") or 0)
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in msg["accountKeys"]]
    idx = keys.index(wallet) if wallet in keys else 0
    sol = (meta["preBalances"][idx] - meta["postBalances"][idx]) / 1e9 - meta.get("fee", 0) / 1e9
    return {"mint": mint, "initial_tokens": tok, "initial_sol": max(0.0, sol)}
WSOL_OWNERS_IGNORE = set()


def _b58(b: bytes) -> str:
    from solders.pubkey import Pubkey
    return str(Pubkey.from_bytes(bytes(b)))


def decode_trades_from_logs(logs: list[str]) -> list[dict]:
    """TradeEvents de pump.fun en los logs: [{mint, sol, tokens, is_buy, price}] (layout estándar)."""
    import base64, struct
    out = []
    for l in logs or []:
        if not l.startswith("Program data: "):
            continue
        try:
            b = base64.b64decode(l[len("Program data: "):])
            if len(b) < 113:
                continue
            sol_amt, tok_amt = struct.unpack_from("<QQ", b, 40); flag = b[56]
            if flag not in (0, 1) or tok_amt == 0:
                continue
            vsol, vtok = struct.unpack_from("<QQ", b, 97)
            out.append({"mint": _b58(b[8:40]), "sol": sol_amt / 1e9, "tokens": tok_amt / 1e6, "is_buy": flag == 1,
                        "price": (vsol / 1e9) / (vtok / 1e6) if vsol and vtok else (sol_amt / 1e9) / (tok_amt / 1e6)})
        except Exception:  # noqa: BLE001
            continue
    return out


def decode_create_from_logs(logs: list[str], wallet: str) -> dict | None:
    """Camino rápido: decodifica el CreateEvent y el TradeEvent (compra inicial) de pump.fun directamente de los
    logs ("Program data: <base64>") de la notificación, sin pedir la transacción. Devuelve
    {mint, price_after (SOL/token), vsol, vtok, initial_sol, initial_tokens} o None."""
    import base64, struct
    blobs = []
    for l in logs or []:
        if l.startswith("Program data: "):
            try: blobs.append(base64.b64decode(l[len("Program data: "):]))
            except Exception: pass  # noqa: BLE001
    mint_b = None
    for b in blobs:
        try:
            o = 8; strs = []
            for _ in range(3):
                n = struct.unpack_from("<I", b, o)[0]; o += 4
                if n > 400: raise ValueError("no es CreateEvent")
                strs.append(b[o:o+n]); o += n
            m = b[o:o+32]; o += 32
            if len(m) == 32 and _b58(m).endswith("pump"):
                mint_b = m; break
        except Exception:  # noqa: BLE001
            continue
    if not mint_b:
        return None
    out = {"mint": _b58(mint_b), "price_after": 0.0, "vsol": 0, "vtok": 0, "initial_sol": 0.0, "initial_tokens": 0.0}
    for b in blobs:
        if len(b) >= 113 and b[8:40] == mint_b:
            try:
                sol_amt, tok_amt = struct.unpack_from("<QQ", b, 40); is_buy = b[56] == 1
                vsol, vtok = struct.unpack_from("<QQ", b, 97)
                if is_buy and vsol > 0 and vtok > 0:
                    out.update({"vsol": vsol, "vtok": vtok, "price_after": (vsol / 1e9) / (vtok / 1e6),
                                "initial_sol": sol_amt / 1e9, "initial_tokens": tok_amt / 1e6})
            except Exception:  # noqa: BLE001
                pass
    if out["price_after"] <= 0:
        out["price_after"] = 30.0 / 1_073_000_000.0
    return out


def parse_swap(tx: dict, wallet: str) -> dict | None:
    """Devuelve {side, mint, sol, tokens, price} si la tx es un swap SOL<->token de `wallet`."""
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return None
    msg = tx["transaction"]["message"]
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in msg["accountKeys"]]
    if wallet not in keys:
        return None
    idx = keys.index(wallet)
    sol_delta = (meta["postBalances"][idx] - meta["preBalances"][idx]) / 1e9 + meta.get("fee", 0) / 1e9
    # tokens del wallet por mint (pre y post)
    def bal(rows):
        out = {}
        for b in rows or []:
            if b.get("owner") == wallet and b.get("mint") != SOL_MINT:
                out[b["mint"]] = out.get(b["mint"], 0.0) + float(b["uiTokenAmount"].get("uiAmount") or 0)
        return out
    pre, post = bal(meta.get("preTokenBalances")), bal(meta.get("postTokenBalances"))
    deltas = {m: post.get(m, 0.0) - pre.get(m, 0.0) for m in set(pre) | set(post)}
    deltas = {m: d for m, d in deltas.items() if abs(d) > 0}
    if not deltas:
        return None
    mint, tok_delta = max(deltas.items(), key=lambda x: abs(x[1]))
    # WSOL envuelto cuenta como SOL: si el wallet movió WSOL, sumarlo
    for b in meta.get("postTokenBalances") or []:
        pass
    if tok_delta > 0 and sol_delta < -0.0005:
        sol = -sol_delta
        return {"side": "buy", "mint": mint, "sol": sol, "tokens": tok_delta, "price": sol / tok_delta}
    if tok_delta < 0 and sol_delta > 0.0005:
        return {"side": "sell", "mint": mint, "sol": sol_delta, "tokens": -tok_delta, "price": sol_delta / -tok_delta}
    return None


class HeliusWatch(threading.Thread):
    def __init__(self, api_key: str, wallets: list[str], commitment: str = "processed"):
        super().__init__(daemon=True, name="heliuswatch")
        self.key = api_key
        self.ws_url = f"wss://mainnet.helius-rpc.com/?api-key={api_key}"
        self.rpc_url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
        self.wallets = list(dict.fromkeys(wallets))
        self.sub_to_wallet: dict[int, str] = {}
        self.events: deque = deque(maxlen=5000)
        self.creates: deque = deque(maxlen=2000)     # creaciones de tokens por billeteras seguidas (fábricas)
        self.sigs: queue.Queue = queue.Queue()
        self.connected = False
        self.notifications = 0
        self.parsed = 0
        self.skipped = 0
        self.errors: deque = deque(maxlen=20)
        self._stop = threading.Event()
        self.ws = None
        self.seen: deque = deque(maxlen=5000)
        self.commitment = commitment
        self.fast_creates = 0

    def stop(self) -> None:
        self._stop.set()
        try:
            if self.ws: self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------- RPC ----------
    def _get_tx(self, sig: str) -> dict | None:
        for i in range(6):
            try:
                r = requests.post(self.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                                                      "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}]}, timeout=15)
                res = r.json().get("result")
                if res:
                    return res
            except Exception as e:  # noqa: BLE001
                self.errors.append(f"{time.strftime('%H:%M:%S')} getTransaction: {e}")
            time.sleep(0.7 + 0.5 * i)
        return None

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                sig, wallet, t_seen = self.sigs.get(timeout=1)
            except queue.Empty:
                continue
            tx = self._get_tx(sig)
            if not tx:
                continue
            cr = parse_create(tx, wallet)
            if cr:
                self.creates.append({"ts": time.time(), "seen_ts": t_seen, "block_time": tx.get("blockTime"), "creator": wallet, "sig": sig, **cr})
                log.info("HELIUS create %s… -> %s (lat %.1fs)", wallet[:6], cr["mint"][:8], time.time() - t_seen)
                continue
            ev = parse_swap(tx, wallet)
            if not ev:
                continue
            self.parsed += 1
            self.events.append({"ts": time.time(), "seen_ts": t_seen, "block_time": tx.get("blockTime"), "wallet": wallet, "sig": sig,
                                "mcap_sol": ev["price"] * 1e9, "pool": "helius", "new_balance": None, **ev})
            log.info("HELIUS %s %s %s %.4f SOL @ %.3e (lat %.1fs)", wallet[:6], ev["side"], ev["mint"][:8], ev["sol"], ev["price"], time.time() - t_seen)

    # ---------- WS ----------
    def run(self) -> None:
        import websocket
        threading.Thread(target=self._worker, daemon=True, name="heliusworker").start()
        backoff = 2
        while not self._stop.is_set():
            try:
                self.ws = websocket.create_connection(self.ws_url, timeout=30)
                self.connected = True; backoff = 2
                self.sub_to_wallet.clear(); pending = {}
                for i, w in enumerate(self.wallets):
                    rid = 1000 + i
                    self.ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": "logsSubscribe", "params": [{"mentions": [w]}, {"commitment": self.commitment}]}))
                    pending[rid] = w
                log.info("helius conectado; suscribiendo %d billeteras", len(self.wallets))
                last_ping = time.time()
                while not self._stop.is_set():
                    try:
                        raw = self.ws.recv()
                    except websocket.WebSocketTimeoutException:
                        if time.time() - last_ping > 25:
                            self.ws.ping(); last_ping = time.time()
                        continue
                    if not raw:
                        continue
                    m = json.loads(raw)
                    if "id" in m and m.get("id") in pending:
                        if "result" in m:
                            self.sub_to_wallet[m["result"]] = pending.pop(m["id"])
                        else:
                            self.errors.append(f"sub error: {str(m.get('error'))[:120]}"); pending.pop(m["id"], None)
                        continue
                    if m.get("method") == "logsNotification":
                        self.notifications += 1
                        p = m["params"]; sub = p.get("subscription"); val = (p.get("result") or {}).get("value") or {}
                        sig = val.get("signature"); wallet = self.sub_to_wallet.get(sub)
                        logs = " ".join(val.get("logs") or [])
                        # camino rápido para creaciones: decodificar de los logs, sin esperar ni pedir la tx
                        if sig and wallet and not val.get("err") and "Instruction: Create" in logs and sig not in self.seen:
                            fc = decode_create_from_logs(val.get("logs") or [], wallet)
                            if fc:
                                self.seen.append(sig); self.fast_creates += 1
                                slot = ((p.get("result") or {}).get("context") or {}).get("slot")
                                self.creates.append({"ts": time.time(), "seen_ts": time.time(), "block_time": None, "creator": wallet, "sig": sig, "slot": slot, "fast": True, **fc})
                                log.info("HELIUS create RÁPIDO %s… -> %s slot %s precio %.3e", wallet[:6], fc["mint"][:8], slot, fc["price_after"])
                                continue
                        # solo bajar la tx si los logs muestran creación o swap (las fábricas mandan cientos de transferencias:
                        # bajarlas todas agota la cuota de Helius y devuelve errores)
                        # camino rápido para VENTAS de la billetera seguida (para salir con la fábrica sin esperar confirmación)
                        if sig and wallet and not val.get("err") and "Instruction: Sell" in logs and sig not in self.seen:
                            for tr in decode_trades_from_logs(val.get("logs") or []):
                                if not tr["is_buy"]:
                                    self.events.append({"ts": time.time(), "seen_ts": time.time(), "block_time": None, "wallet": wallet, "sig": sig, "side": "sell",
                                                        "mint": tr["mint"], "sol": tr["sol"], "tokens": tr["tokens"], "price": tr["price"], "fast": True,
                                                        "mcap_sol": tr["price"] * 1e9, "pool": "helius", "new_balance": None})
                                    log.info("HELIUS venta RÁPIDA %s… %s %.3f SOL", wallet[:6], tr["mint"][:8], tr["sol"])
                        relevant = any(k in logs for k in ("Instruction: Create", "Instruction: Buy", "Instruction: Sell", "Swap", "swap"))
                        if sig and wallet and not val.get("err") and relevant and sig not in self.seen:
                            self.seen.append(sig)
                            self.sigs.put((sig, wallet, time.time()))
                        elif not relevant:
                            self.skipped += 1
            except Exception as e:  # noqa: BLE001
                self.connected = False
                self.errors.append(f"{time.strftime('%H:%M:%S')} {str(e)[:150]}")
                log.warning("helius caído: %s; reconecto en %ss", str(e)[:150], backoff)
                try:
                    if self.ws: self.ws.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(backoff); backoff = min(backoff * 2, 60)
        self.connected = False
