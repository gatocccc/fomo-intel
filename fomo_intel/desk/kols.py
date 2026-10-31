"""Consenso de KOLs — prueba del laboratorio (desde 30/10/2026).

Idea de Gastón (30/10): meterse "entre medio" de las billeteras de los nombres conocidos de pump.fun. Lo que midió el backtest
(ops 181–184, `consenso-kols-30-10.md`): copiar la primera compra de cualquiera pierde (22% de acierto, mediana −30%); entrar cuando
ya compraron 4 nombres distintos en menos de 60 min y salir rápido (mitad a 2x = initials, resto afuera a los 30 min) dio +21,7% por
operación (n=40, las dos mitades positivas). Acá se prueba en vivo con US$5 por operación en el lab.

Cómo funciona: escucha las billeteras de `desk/kols.json` por Helius (logsSubscribe, la misma infraestructura del modo seguidor),
cuenta compras de billeteras distintas por token dentro de la ventana y, al llegar a `k`, escribe una decisión en
`state/plan_lab/auto/` que el motor del lab ejecuta (compra en SOL; venta 50% a 2x; tope 30 min; stop −50% de seguridad;
`brain: false` para que el cerebro no la toque). Estado para el panel y las sesiones: `state/desk/kols.json`; bitácora: `state/desk/kols_log.jsonl`.
Corre dentro de fomo-radar (ver radar.cycle). Modo: `LAB_KOLS=live|shadow` (shadow registra pero no compra).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from pathlib import Path

import requests

log = logging.getLogger("kols")
CFG = Path("desk/kols.json")
STATE = Path("state/desk/kols.json")
LOG = Path("state/desk/kols_log.jsonl")
AUTO = Path("state/plan_lab/auto")
PROCESSED = Path("state/plan_lab/processed.json")
LAB_POS = Path("state/plan_lab/positions.json")
JUP_PRICE = "https://api.jup.ag/price/v3"
SOL_MINT = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY8NnhrbPKjtaFq1"}


def _jl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


class KolConsensus:
    """Una prueba de consenso. La misma clase corre dos listas (30/10): KOLs de TYGR (desk/kols.json, k=4, motivo kol_consensus)
    y billeteras buenas medidas fuera de muestra (desk/good_wallets.json, k=3, motivo good_wallets, salida TP 2x / SL 30% / 6 h)."""

    def __init__(self, cfg: Path | None = None, state: Path | None = None, logp: Path | None = None, reason: str = "kol_consensus",
                 extra: Path | None = None):
        self.CFG = cfg or CFG; self.STATE = state or STATE; self.LOG = logp or LOG; self.reason = reason
        # 31/10: lista adicional escrita por ops en el servidor (state/, no viaja por el repo): perfiles con audiencia de la app FOMO
        self.EXTRA = extra
        self.extra_mtime = 0.0
        self.lock = threading.RLock()
        self._pump_thread: threading.Thread | None = None
        self.mode = os.getenv("LAB_KOLS", "live")
        self.cfg: dict = {}
        self.cfg_mtime = 0.0
        self.names: dict[str, str] = {}
        self.watch = None
        self.seen_sigs: set[str] = set()
        self.buys: dict[str, dict[str, dict]] = defaultdict(dict)   # mint -> wallet -> {ts, sol, name}
        self.triggered: dict[str, float] = {}                        # mint -> ts del gatillo (no repetir en 24 h)
        self.sol_usd = 0.0
        self.sol_ts = 0.0
        self.events = 0
        self.started = time.time()
        self._load_cfg()
        self._restore()

    # ----- config / estado -----
    def _load_cfg(self) -> bool:
        try:
            mt = self.CFG.stat().st_mtime
        except FileNotFoundError:
            return False
        emt = 0.0
        if self.EXTRA is not None:
            try:
                emt = self.EXTRA.stat().st_mtime
            except FileNotFoundError:
                emt = 0.0
        if mt == self.cfg_mtime and emt == self.extra_mtime:
            return False
        self.cfg = json.load(open(self.CFG))
        self.cfg_mtime = mt; self.extra_mtime = emt
        self.names = {w["wallet"]: w["name"] for w in self.cfg.get("wallets", [])}
        if emt:
            try:
                for w in json.load(open(self.EXTRA)).get("wallets", []):
                    self.names.setdefault(w["wallet"], w["name"])
            except Exception as e:  # noqa: BLE001
                log.warning("kols: lista extra ilegible %s: %s", self.EXTRA, e)
        return True

    def _restore(self) -> None:
        try:
            s = json.load(open(self.STATE))
            self.triggered = {m: float(t) for m, t in (s.get("triggered") or {}).items()}
            for m, ws in (s.get("buys") or {}).items():
                self.buys[m] = ws
        except Exception:  # noqa: BLE001
            pass

    def _ensure_watch(self) -> None:
        changed = self._load_cfg()
        wallets = list(self.names)
        if self.watch is not None and not changed:
            return
        key = os.getenv("HELIUS_API_KEY", "")
        if not key or not wallets:
            return
        if self.watch is not None:
            try:
                self.watch.stop()
            except Exception:  # noqa: BLE001
                pass
        from ..live.helius_watch import HeliusWatch
        self.watch = HeliusWatch(key, wallets, commitment="confirmed")
        self.watch.start()
        log.info("kols: escuchando %d billeteras (k=%s, ventana %s min, US$%s por operación, modo %s)",
                 len(wallets), self.cfg.get("k"), self.cfg.get("window_min"), self.cfg.get("size_usd"), self.mode)

    # ----- precios -----
    def _sol_price(self) -> float:
        if time.time() - self.sol_ts < 120 and self.sol_usd:
            return self.sol_usd
        try:
            h = {"x-api-key": os.getenv("JUPITER_API_KEY", "")} if os.getenv("JUPITER_API_KEY") else {}
            r = requests.get(JUP_PRICE, params={"ids": SOL_MINT}, headers=h, timeout=10).json()
            px = float((r.get(SOL_MINT) or {}).get("usdPrice") or 0)
            if px:
                self.sol_usd, self.sol_ts = px, time.time()
        except Exception as e:  # noqa: BLE001
            log.warning("kols: precio de SOL: %s", e)
        return self.sol_usd or 95.0

    # ----- lab -----
    def _lab_open(self, reason: str | None = None) -> int:
        reason = reason or self.reason
        try:
            pos = json.load(open(LAB_POS))
            pos = pos.values() if isinstance(pos, dict) else pos
            return sum(1 for p in pos if p.get("reason") == reason)
        except Exception:  # noqa: BLE001
            return 0

    def _verdict(self, reason: str | None = None) -> tuple[int, float, float]:
        """Cierres del lab con motivo kol_consensus: (n, retorno medio, P&L US$). Freno propio: con ≥10 cierres y retorno medio
        negativo la prueba pasa sola a modo sombra (registra, no compra). Es el criterio 'si aprueba en el lab pasa al otro'."""
        try:
            rows = [json.loads(l) for l in Path("state/plan_lab/closed.jsonl").read_text().splitlines() if l.strip()]
        except Exception:  # noqa: BLE001
            return 0, 0.0, 0.0
        rows = [r for r in rows if r.get("reason") == (reason or self.reason)]
        if not rows:
            return 0, 0.0, 0.0
        return len(rows), sum(float(r.get("ret") or 0) for r in rows) / len(rows), sum(float(r.get("pnl_usd") or 0) for r in rows)

    def _lab_sol(self) -> float:
        try:
            return float(json.load(open("state/plan_lab_summary.json")).get("cash_sol") or 0)
        except Exception:  # noqa: BLE001
            return 0.0

    # ----- ciclo -----
    def _consume(self) -> None:
        """Consume los eventos nuevos del canal y dispara en el acto. 31/10: antes esto corría una vez por minuto dentro del ciclo del
        radar y las compras se veían 15–60 s tarde (caso LUMI: 48 s). Ahora lo corre un hilo propio cada 0,5 s."""
        if self.watch is None:
            return
        k = int(self.cfg.get("k", 4)); win = float(self.cfg.get("window_min", 60)) * 60
        min_sol = float(self.cfg.get("min_sol", 0.02))
        big_sol = float(self.cfg.get("big_sol", 0) or 0)                      # 0 = gatillo de compra grande apagado
        big_cap = float(self.cfg.get("big_max_mcap_usd", 500_000) or 0)
        now = time.time()
        with self.lock:
            for ev in list(self.watch.events):
                sig = ev.get("sig")
                if not sig or sig in self.seen_sigs:
                    continue
                self.seen_sigs.add(sig)
                if len(self.seen_sigs) > 20000:
                    self.seen_sigs = set(list(self.seen_sigs)[-10000:])
                if ev.get("side") != "buy" or ev.get("mint") in STABLES or float(ev.get("sol") or 0) < min_sol:
                    continue
                self.events += 1
                w = ev["wallet"]; m = ev["mint"]; ts = float(ev.get("block_time") or ev.get("ts") or now)
                sol = round(float(ev.get("sol") or 0), 4)
                mcap_usd = float(ev.get("mcap_sol") or 0) * self._sol_price()
                if w not in self.buys[m]:
                    self.buys[m][w] = {"ts": ts, "sol": sol, "name": self.names.get(w, w[:6])}
                    _jl(self.LOG, {"ts": now, "kind": "buy", "mint": m, "wallet": w, "name": self.names.get(w, w[:6]), "sol": sol,
                              "mcap_usd": round(mcap_usd), "n": len(self.buys[m]), "lat_s": round(now - ts, 1)})
                else:
                    self.buys[m][w]["sol"] = round(self.buys[m][w]["sol"] + sol, 4)
                # gatillo 2 (31/10, caso LUMI): un solo nombre comprando grande y temprano
                if big_sol and sol >= big_sol and (not big_cap or 0 < mcap_usd <= big_cap):
                    key = f"big:{m}"
                    if not (key in self.triggered and now - self.triggered[key] < 86400):
                        self.triggered[key] = now
                        self._fire_big(m, w, sol, mcap_usd, ts, now)
            # gatillo 1: k billeteras distintas dentro de la ventana
            for m, ws in list(self.buys.items()):
                live = {w: b for w, b in ws.items() if now - b["ts"] <= win}
                if len(live) < k or (m in self.triggered and now - self.triggered[m] < 86400):
                    continue
                self.triggered[m] = now
                self._fire(m, live, now)

    def _pump(self) -> None:
        while True:
            try:
                self._consume()
            except Exception as e:  # noqa: BLE001
                log.exception("kols hilo: %s", e)
            time.sleep(0.5)

    def step(self) -> None:
        self._ensure_watch()
        if self.watch is None:
            return
        if self._pump_thread is None or not self._pump_thread.is_alive():
            self._pump_thread = threading.Thread(target=self._pump, daemon=True, name=f"kols-{self.reason}")
            self._pump_thread.start()
        k = int(self.cfg.get("k", 4)); win = float(self.cfg.get("window_min", 60)) * 60
        now = time.time()
        with self.lock:
            self._consume()
            # podar ventanas viejas
            for m in list(self.buys):
                self.buys[m] = {w: b for w, b in self.buys[m].items() if now - b["ts"] <= win}
                if not self.buys[m]:
                    del self.buys[m]
            self.triggered = {m: t for m, t in self.triggered.items() if now - t < 7 * 86400}
            # estado para el panel
            n, ret, pnl = self._verdict()
            nb, retb, pnlb = self._verdict(self.reason + "_big")
            st = {"ts": now, "mode": self.mode, "verdict": {"n": n, "ret": round(ret, 4), "pnl_usd": round(pnl, 2), "halted": n >= 10 and ret < 0},
                  "verdict_big": {"n": nb, "ret": round(retb, 4), "pnl_usd": round(pnlb, 2), "halted": nb >= 10 and retb < 0},
                  "k": k, "window_min": win / 60, "size_usd": self.cfg.get("size_usd"), "big_sol": self.cfg.get("big_sol"),
                  "big_max_mcap_usd": self.cfg.get("big_max_mcap_usd"), "wallets": len(self.names),
                  "connected": bool(getattr(self.watch, "connected", False)), "notifications": getattr(self.watch, "notifications", 0),
                  "buys_seen": self.events, "errors": list(getattr(self.watch, "errors", []))[-3:], "started": self.started,
                  "fast_thread": bool(self._pump_thread and self._pump_thread.is_alive()),
                  "hot": sorted(({"mint": m, "n": len(ws), "who": [b["name"] for b in ws.values()], "last": max(b["ts"] for b in ws.values())}
                                 for m, ws in self.buys.items() if len(ws) >= 2), key=lambda x: -x["n"])[:15],
                  "triggered": {m: t for m, t in self.triggered.items()},
                  "buys": {m: ws for m, ws in self.buys.items()}}
        self.STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(st, ensure_ascii=False)); tmp.replace(self.STATE)

    def _fire_big(self, mint: str, wallet: str, sol: float, mcap_usd: float, ts: float, now: float) -> None:
        """Gatillo de compra grande (31/10, caso LUMI: tvdj compró 14,7 SOL a mcap chica y el token hizo 2x en dos horas; el consenso
        exigía 4 nombres y no disparó). Motivo propio `<reason>_big` para que el post-mortem lo mida aparte del consenso."""
        name = self.names.get(wallet, wallet[:6]); reason = self.reason + "_big"
        row = {"ts": now, "kind": "trigger_big", "mint": mint, "who": [name], "sol": sol, "mcap_usd": round(mcap_usd), "lat_s": round(now - ts, 1), "mode": self.mode}
        size_usd = float(self.cfg.get("big_size_usd", self.cfg.get("size_usd", 5))); max_open = int(self.cfg.get("big_max_open", 2))
        if self.mode != "live" or not self.cfg.get("big_live", False):
            row["skip"] = "shadow"; _jl(self.LOG, row); return   # 31/10 ops 206: backtest 30 d negativo (−14,6%/op) → solo registra
        n, ret, pnl = self._verdict(reason)
        if n >= 10 and ret < 0:
            row["skip"] = f"freno: {n} cierres, retorno medio {ret:+.1%}, P&L US${pnl:+.2f} → modo sombra"; _jl(self.LOG, row); return
        if self._lab_open(reason) >= max_open:
            row["skip"] = f"max_open {max_open}"; _jl(self.LOG, row); return
        sol_size = round(size_usd / self._sol_price(), 4)
        if self._lab_sol() < sol_size + 0.03:
            row["skip"] = f"sin SOL en el lab ({self._lab_sol():.3f})"; _jl(self.LOG, row); return
        did = f"big-{int(now)}-{mint[:6]}"
        thesis = (f"Big early buy by a known name: {name} bought {sol:.1f} SOL at about ${mcap_usd/1000:.0f}K market cap. "
                  f"Testing whether one audience profile sizing in early is the real signal (LUMI case, 30/10). "
                  f"Exit: 50% at 2x, rest out after 30 min, safety stop -50%.")
        dec = {"id": did, "title": f"Big buy by {name}: {mint[:6]}", "journal": f"Automatic lab buy (big-buy trigger): {thesis}",
               "orders": [{"action": "buy", "mint": mint, "symbol": mint[:6], "sol": sol_size, "stop": 0.5, "trail": 0.9, "trail_after": 99,
                           "tp": [[2.0, 0.5]], "max_h": 0.5, "reason": reason, "thesis": thesis},
                          {"action": "set", "mint": mint, "brain": False}]}
        AUTO.mkdir(parents=True, exist_ok=True)
        (AUTO / f"{did}.json").write_text(json.dumps(dec, ensure_ascii=False, indent=1))
        row["decision"] = did; row["size_sol"] = sol_size
        _jl(self.LOG, row)
        log.info("kols GATILLO GRANDE %s: %s %.1f SOL @ US$%.0fK → %s", mint[:8], name, sol, mcap_usd / 1000, did)

    def _fire(self, mint: str, ws: dict, now: float) -> None:
        who = sorted(ws.values(), key=lambda b: b["ts"])
        names = [b["name"] for b in who]
        span = (who[-1]["ts"] - who[0]["ts"]) / 60
        row = {"ts": now, "kind": "trigger", "mint": mint, "who": names, "span_min": round(span, 1), "mode": self.mode}
        size_usd = float(self.cfg.get("size_usd", 5)); max_open = int(self.cfg.get("max_open", 3))
        if self.mode != "live":
            row["skip"] = "shadow"; _jl(self.LOG, row); log.info("kols sombra: %s %s", mint[:8], names); return
        n, ret, pnl = self._verdict()
        if n >= 10 and ret < 0:
            row["skip"] = f"freno: {n} cierres, retorno medio {ret:+.1%}, P&L US${pnl:+.2f} → modo sombra"; _jl(self.LOG, row)
            log.warning("kols: %s", row["skip"]); return
        if self._lab_open() >= max_open:
            row["skip"] = f"max_open {max_open}"; _jl(self.LOG, row); return
        sol = round(size_usd / self._sol_price(), 4)
        if self._lab_sol() < sol + 0.03:
            row["skip"] = f"sin SOL en el lab ({self._lab_sol():.3f})"; _jl(self.LOG, row); return
        did = f"{'kols' if self.reason == 'kol_consensus' else 'good'}-{int(now)}-{mint[:6]}"
        if self.reason == "kol_consensus":
            thesis = (f"Consenso de KOLs: {len(names)} nombres conocidos compraron en {span:.0f} min ({', '.join(names)}). "
                      f"Entrada entre los nombres y la audiencia; salida 50% a 2x (initials) y el resto afuera a los 30 min. "
                      f"Backtest 30 d (ops 184): +21,7% por operación, 48% de acierto, n=40.")
            journal = f"Compra automática del laboratorio: {thesis} Riesgo aceptado: los KOLs ya ganan 20–100% cuando entra el cuarto; si la audiencia no llega, el tope de 30 min nos saca."
            title = f"Consenso KOLs {mint[:6]}"
            buy = {"stop": 0.5, "trail": 0.9, "trail_after": 99, "tp": [[2.0, 0.5]], "max_h": 0.5}
        else:
            ex = self.cfg.get("exit") or {}
            thesis = (f"{len(names)} wallets with a proven record bought the same token within {span:.0f} min ({', '.join(names)}). "
                      f"Testing whether several good wallets piling in is a real signal. Exit: sell at 2x, stop -30%, out after 6 h. "
                      f"Backtest: {self.cfg.get('backtest', '')}.")
            journal = f"Automatic lab buy (good wallets, k={self.cfg.get('k')}): {thesis}"
            title = f"Good wallets pile in: {mint[:6]}"
            buy = {"stop": float(ex.get("stop", 0.3)), "trail": 0.9, "trail_after": 99, "tp": ex.get("tp", [[2.0, 1.0]]), "max_h": float(ex.get("max_h", 6))}
        dec = {"id": did, "title": title, "journal": journal,
               "orders": [{"action": "buy", "mint": mint, "symbol": mint[:6], "sol": sol, **buy, "reason": self.reason, "thesis": thesis},
                          {"action": "set", "mint": mint, "brain": False}]}
        AUTO.mkdir(parents=True, exist_ok=True)
        (AUTO / f"{did}.json").write_text(json.dumps(dec, ensure_ascii=False, indent=1))
        row["decision"] = did; row["sol"] = sol
        _jl(self.LOG, row)
        log.info("kols GATILLO %s: %s → decisión %s (%.4f SOL)", mint[:8], names, did, sol)
