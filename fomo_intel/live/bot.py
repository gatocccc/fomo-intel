"""Bot en vivo. Ejecutar:  python -m fomo_intel.live.bot   (lee .env del directorio actual si existe).

Ciclo (cada segundo):
  1. tokens nuevos que llegaron a T2 -> features -> (si pasan el proxy) riesgo en Solana Tracker -> candidato
  2. candidatos que llegaron a T3 -> confirmación -> frenos -> COMPRA
  3. posiciones abiertas -> precio actual -> stop / trailing / take profit / tiempo -> VENTA
  4. cada 30 s: resumen para el dashboard; recarga de state/control.json
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from .config import Env, LiveParams
from .executor import PaperExecutor, RealExecutor
from .portfolio import Portfolio
from .signals import STClient, confirmed, enrich, features_at_t2
from .stream import PumpStream

log = logging.getLogger("live")


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Bot:
    def __init__(self):
        self.env = Env()
        self.p = LiveParams.load(self.env.state_dir)
        self.p.save(self.env.state_dir)          # deja el control.json completo para editar
        self.state = self.env.state_dir
        self.st = STClient(self.env.solanatracker_api_key)
        self.port = Portfolio(self.state, self.p)
        self.stream = PumpStream(keep_seconds=420.0)
        self.candidates: dict[str, object] = {}     # mint -> Features esperando T3
        self.creators: dict[str, list[float]] = self._load_creators()
        self.sol_usd = 0.0
        self.pub = ""
        if self.p.mode == "real":
            from .wallet import Rpc, load_or_create
            kp = load_or_create(self.env.wallet_file)
            self.pub = str(kp.pubkey())
            self.exe = RealExecutor(self.p, kp, Rpc(self.env.rpc_url), self.env.solanatracker_api_key)
        else:
            self.exe = PaperExecutor(self.p, payer=self._wallet_pubkey(), st_api_key=self.env.solanatracker_api_key)
        self._last_reload = self._last_summary = self._last_heartbeat = 0.0
        self._sell_backoff: dict[str, float] = {}
        self._price_poll: dict[str, float] = {}
        self.running = True

    # ---------- utilidades ----------
    def _load_creators(self) -> dict:
        f = self.state / "creators.json"
        try:
            return json.load(open(f)) if f.exists() else {}
        except json.JSONDecodeError:
            return {}

    def _note_creator(self, creator: str, ts: float) -> int:
        lst = [t for t in self.creators.get(creator, []) if ts - t < 86400]
        prior = len(lst)
        lst.append(ts)
        self.creators[creator] = lst
        return prior

    def _save_creators(self) -> None:
        cut = time.time() - 86400
        self.creators = {c: [t for t in ts if t > cut] for c, ts in self.creators.items() if any(t > cut for t in ts)}
        json.dump(self.creators, open(self.state / "creators.json", "w"))

    def _reload(self) -> None:
        newp = LiveParams.load(self.state)
        if newp.mode != self.p.mode:
            log.warning("cambio de modo %s -> %s: requiere reiniciar el servicio; sigo en %s", self.p.mode, newp.mode, self.p.mode)
            newp.mode = self.p.mode
        self.p = newp
        self.port.p = newp
        self.exe.p = newp

    def _wallet_pubkey(self) -> str:
        if self.pub:
            return self.pub
        f = self.env.wallet_file
        if f.exists():
            try: return json.load(open(f))["pubkey"]
            except Exception: pass  # noqa: BLE001
        return ""

    # ---------- 1) evaluación al T2 ----------
    def step_evaluate(self, now: float) -> None:
        for st in self.stream.young(60, 420):
            if st.evaluated:
                continue
            from .signals import t2_of
            if now < t2_of(st.created_ts, self.p.eval_min):
                continue
            st.evaluated = True
            prior = self._note_creator(st.creator, st.created_ts)
            f = features_at_t2(st, self.p, self.sol_usd, prior)
            if not f.passes_proxy:
                # solo se registran los que al menos se movieron, para no llenar el log con miles de tokens muertos
                if f.move >= 2.0 or f.n_buyers_120s >= 20:
                    self.port.log_signal(f.as_dict(), "descartado_t2")
                st.decided = True
                continue
            f = enrich(f, self.p, self.st)
            if not f.passes:
                self.port.log_signal(f.as_dict(), "descartado_riesgo")
                st.decided = True
                continue
            self.candidates[st.mint] = f
            log.info("CANDIDATO %s move=%.1fx compradores=%d vol=$%.0f snipers=%s -> confirma a T3", f.symbol, f.move, f.n_buyers_120s, f.vol_usd, f.n_snipers_st)

    # ---------- 2) confirmación y compra al T3 ----------
    def step_enter(self, now: float) -> None:
        for mint, f in list(self.candidates.items()):
            if now < f.t3:
                continue
            self.candidates.pop(mint)
            st = self.stream.snapshot(mint)
            if not st:
                self.port.log_signal(f.as_dict(), "perdido_stream"); continue
            st.decided = True
            ok, px3 = confirmed(st, f, self.p)
            d = f.as_dict(); d["px_t3"] = px3; d["px_t3_vs_t2"] = round(px3 / f.px_t2, 3) if f.px_t2 else None
            if not ok:
                self.port.log_signal(d, "no_confirmado"); continue
            why_not = self.port.stop_reason()
            if why_not:
                self.port.log_signal(d, f"freno: {why_not}"); log.info("señal %s no operada: %s", f.symbol, why_not); continue
            if mint in self.port.positions:
                continue
            if self.sol_usd <= 0:
                self.port.log_signal(d, "sin precio SOL"); continue
            size_sol = self.p.size_usd / self.sol_usd
            if self.p.mode == "real":
                bal = self.exe.sol_balance()
                if bal - size_sol < self.p.min_sol_reserve:
                    self.port.log_signal(d, f"sin saldo: {bal:.4f} SOL"); log.warning("sin saldo para operar: %.4f SOL", bal); continue
            ref = st.last_price or px3
            fill = self.exe.buy(mint, size_sol, ref)
            self.port.log_fill(fill, self.p.mode, "entrada", self.sol_usd)
            if not fill.ok:
                self.port.log_signal(d, f"compra fallida: {fill.error}"); log.warning("compra %s falló: %s", f.symbol, fill.error); continue
            self.port.open(fill, f.symbol, self.sol_usd)
            self.stream.pin(mint)
            self.port.log_signal(d, "COMPRADO")
            log.info("COMPRA %s %.4f SOL (US$%.0f) a %.3e SOL/token slippage=%+.1f%% lat=%.1fs sig=%s",
                     f.symbol, fill.sol, fill.sol * self.sol_usd, fill.price, fill.slippage_pct, fill.latency_s, fill.sig)

    # ---------- 3) posiciones ----------
    def _current_price(self, pos, now: float) -> float:
        st = self.stream.snapshot(pos.mint)
        if st and st.last_ts and now - st.last_ts < 20 and st.last_price > 0:
            return st.last_price
        # stream callado (token graduado o sin operaciones): consulto precio cada 15 s
        if now - self._price_poll.get(pos.mint, 0) >= 15:
            self._price_poll[pos.mint] = now
            usd = self.st.price(pos.mint)
            if usd and self.sol_usd > 0:
                pos.last_price, pos.last_ts = usd / self.sol_usd, now
                return pos.last_price
        return pos.last_price

    def step_positions(self, now: float) -> None:
        for mint, pos in list(self.port.positions.items()):
            px = self._current_price(pos, now)
            if px <= 0:
                continue
            pos.last_price, pos.last_ts = px, now
            pos.peak_price = max(pos.peak_price, px)
            why, frac = self.port.exit_decision(pos, px, now)
            if not why:
                continue
            if now < self._sell_backoff.get(mint, 0):
                continue
            tokens = pos.tokens if frac >= 1.0 else min(pos.tokens, pos.tokens_initial * frac)
            fill = self.exe.sell(mint, tokens, px)
            self.port.log_fill(fill, self.p.mode, why, self.sol_usd)
            if not fill.ok:
                self._sell_backoff[mint] = now + 10
                log.warning("venta %s (%s) falló: %s", pos.symbol, why, fill.error)
                if "sin tokens" in fill.error:   # ya no hay nada que vender: cerrar la posición como está
                    self.port.apply_sell(pos, fill, why)
                    self.stream.unpin(mint)
                continue
            closed = self.port.apply_sell(pos, fill, why)
            log.info("VENTA %s %s %.0f%% a %.2fx slippage=%+.1f%% -> %.4f SOL%s", pos.symbol, why, fill.tokens / pos.tokens_initial * 100,
                     fill.price / pos.entry_price, fill.slippage_pct, fill.sol, " [CERRADA]" if closed else "")
            if closed:
                self.stream.unpin(mint)

    # ---------- 4) resumen ----------
    def step_summary(self, now: float) -> None:
        wallet_sol = None
        if self.p.mode == "real":
            try: wallet_sol = round(self.exe.sol_balance(), 4)
            except Exception: pass  # noqa: BLE001
        self.port.summary({"wallet": self._wallet_pubkey(), "wallet_sol": wallet_sol, "sol_usd": self.sol_usd,
                           "stream_connected": self.stream.connected, "stream_msgs": self.stream.msgs,
                           "tokens_seen": self.stream.creates, "tokens_tracked": len(self.stream.tokens),
                           "candidates": [f.symbol for f in self.candidates.values()],
                           "st_requests": self.st.requests_made, "stream_errors": list(self.stream.errors)[-5:],
                           "stream_counts": dict(self.stream.counts), "stream_samples": list(self.stream.samples),
                           "params": {k: getattr(self.p, k) for k in ("mode", "size_usd", "max_open", "daily_loss_usd", "total_loss_usd", "max_trades", "max_slippage_pct")}})
        self._save_creators()

    # ---------- loop ----------
    def run(self) -> None:
        log.info("arranca bot modo=%s tamaño=US$%.0f máx_abiertas=%d billetera=%s", self.p.mode, self.p.size_usd, self.p.max_open, self._wallet_pubkey() or "-")
        self.stream.start()
        while self.running:
            now = time.time()
            try:
                if now - self._last_reload > 30:
                    self._reload(); self._last_reload = now
                    self.sol_usd = self.st.sol_usd() or self.sol_usd
                if self.sol_usd > 0:
                    self.step_evaluate(now)
                    self.step_enter(now)
                self.step_positions(now)
                if now - self._last_summary > 30:
                    self.step_summary(now); self._last_summary = now
                if now - self._last_heartbeat > 300:
                    log.info("latido: stream=%s tokens_vistos=%d seguidos=%d candidatos=%d abiertas=%d cerradas=%d st_requests=%d SOL=$%.0f",
                             self.stream.connected, self.stream.creates, len(self.stream.tokens), len(self.candidates),
                             len(self.port.positions), len(self.port.closed()), self.st.requests_made, self.sol_usd)
                    self._last_heartbeat = now
            except Exception as e:  # noqa: BLE001
                log.exception("error en el ciclo: %s", e)
                time.sleep(2)
            time.sleep(1.0)
        self.stream.stop()
        self.port.save()


def main() -> None:
    load_dotenv()
    env = Env()
    env.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    bot = Bot()

    def _stop(*_):
        log.info("apagando..."); bot.running = False
    signal.signal(signal.SIGTERM, _stop); signal.signal(signal.SIGINT, _stop)
    bot.run()


if __name__ == "__main__":
    main()
