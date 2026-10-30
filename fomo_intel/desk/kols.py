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
    def __init__(self):
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
            mt = CFG.stat().st_mtime
        except FileNotFoundError:
            return False
        if mt == self.cfg_mtime:
            return False
        self.cfg = json.load(open(CFG))
        self.cfg_mtime = mt
        self.names = {w["wallet"]: w["name"] for w in self.cfg.get("wallets", [])}
        return True

    def _restore(self) -> None:
        try:
            s = json.load(open(STATE))
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
    def _lab_open(self) -> int:
        try:
            pos = json.load(open(LAB_POS))
            pos = pos.values() if isinstance(pos, dict) else pos
            return sum(1 for p in pos if p.get("reason") == "kol_consensus")
        except Exception:  # noqa: BLE001
            return 0

    def _lab_sol(self) -> float:
        try:
            return float(json.load(open("state/plan_lab_summary.json")).get("cash_sol") or 0)
        except Exception:  # noqa: BLE001
            return 0.0

    # ----- ciclo -----
    def step(self) -> None:
        self._ensure_watch()
        if self.watch is None:
            return
        k = int(self.cfg.get("k", 4)); win = float(self.cfg.get("window_min", 60)) * 60
        min_sol = float(self.cfg.get("min_sol", 0.02))
        now = time.time()
        # 1) consumir eventos nuevos del canal
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
            if w not in self.buys[m]:
                self.buys[m][w] = {"ts": ts, "sol": round(float(ev.get("sol") or 0), 4), "name": self.names.get(w, w[:6])}
                _jl(LOG, {"ts": now, "kind": "buy", "mint": m, "wallet": w, "name": self.names.get(w, w[:6]), "sol": self.buys[m][w]["sol"],
                          "n": len(self.buys[m]), "lat_s": round(now - ts, 1)})
        # 2) podar ventanas viejas
        for m in list(self.buys):
            self.buys[m] = {w: b for w, b in self.buys[m].items() if now - b["ts"] <= win}
            if not self.buys[m]:
                del self.buys[m]
        # 3) gatillo: k billeteras distintas dentro de la ventana
        for m, ws in list(self.buys.items()):
            if len(ws) < k or (m in self.triggered and now - self.triggered[m] < 86400):
                continue
            self.triggered[m] = now
            self._fire(m, ws, now)
        self.triggered = {m: t for m, t in self.triggered.items() if now - t < 7 * 86400}
        # 4) estado para el panel
        st = {"ts": now, "mode": self.mode, "k": k, "window_min": win / 60, "size_usd": self.cfg.get("size_usd"), "wallets": len(self.names),
              "connected": bool(getattr(self.watch, "connected", False)), "notifications": getattr(self.watch, "notifications", 0),
              "buys_seen": self.events, "errors": list(getattr(self.watch, "errors", []))[-3:], "started": self.started,
              "hot": sorted(({"mint": m, "n": len(ws), "who": [b["name"] for b in ws.values()], "last": max(b["ts"] for b in ws.values())}
                             for m, ws in self.buys.items() if len(ws) >= 2), key=lambda x: -x["n"])[:15],
              "triggered": {m: t for m, t in self.triggered.items()},
              "buys": {m: ws for m, ws in self.buys.items()}}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(st, ensure_ascii=False)); tmp.replace(STATE)

    def _fire(self, mint: str, ws: dict, now: float) -> None:
        who = sorted(ws.values(), key=lambda b: b["ts"])
        names = [b["name"] for b in who]
        span = (who[-1]["ts"] - who[0]["ts"]) / 60
        row = {"ts": now, "kind": "trigger", "mint": mint, "who": names, "span_min": round(span, 1), "mode": self.mode}
        size_usd = float(self.cfg.get("size_usd", 5)); max_open = int(self.cfg.get("max_open", 3))
        if self.mode != "live":
            row["skip"] = "shadow"; _jl(LOG, row); log.info("kols sombra: %s %s", mint[:8], names); return
        if self._lab_open() >= max_open:
            row["skip"] = f"max_open {max_open}"; _jl(LOG, row); return
        sol = round(size_usd / self._sol_price(), 4)
        if self._lab_sol() < sol + 0.03:
            row["skip"] = f"sin SOL en el lab ({self._lab_sol():.3f})"; _jl(LOG, row); return
        did = f"kols-{int(now)}-{mint[:6]}"
        thesis = (f"Consenso de KOLs: {len(names)} nombres conocidos compraron en {span:.0f} min ({', '.join(names)}). "
                  f"Entrada entre los nombres y la audiencia; salida 50% a 2x (initials) y el resto afuera a los 30 min. "
                  f"Backtest 30 d (ops 184): +21,7% por operación, 48% de acierto, n=40.")
        dec = {"id": did, "title": f"Consenso KOLs {mint[:6]}",
               "journal": f"Compra automática del laboratorio: {thesis} Riesgo aceptado: los KOLs ya ganan 20–100% cuando entra el cuarto; si la audiencia no llega, el tope de 30 min nos saca.",
               "orders": [{"action": "buy", "mint": mint, "symbol": mint[:6], "sol": sol, "stop": 0.5, "trail": 0.9, "trail_after": 99,
                           "tp": [[2.0, 0.5]], "max_h": 0.5, "reason": "kol_consensus", "thesis": thesis},
                          {"action": "set", "mint": mint, "brain": False}]}
        AUTO.mkdir(parents=True, exist_ok=True)
        (AUTO / f"{did}.json").write_text(json.dumps(dec, ensure_ascii=False, indent=1))
        row["decision"] = did; row["sol"] = sol
        _jl(LOG, row)
        log.info("kols GATILLO %s: %s → decisión %s (%.4f SOL)", mint[:8], names, did, sol)
