"""Grilla en BTC (vender volatilidad en rango) — prueba real del laboratorio (31/10/2026).

Origen: Gastón (31/10 00:16–00:43): "al bot le falta acción de corto plazo… seguimos encontrando motivos para no hacer". Todas las
señales de dirección a horas (perps 1 h, rebotes, rupturas, copiar traders, Nasdaq→cripto, consenso de KOLs) perdieron contra los
costos. Lo que opera todos los días sin adivinar la dirección es cobrar por absorber los vaivenes dentro de una banda: una grilla.

Backtest (ops 208–210, velas de 1 min de Binance, 30 d, costos reales de Jupiter Perps 0,06% por lado + 0,05% slippage + ~0,01%/h
de interés, con la restricción de Jupiter: UN largo y UN corto como máximo por mercado):
  - BTC, centro = media de 2 h, paso 0,8%, corte a 3% del centro: +5,9% en 30 d a 1x, 15 cierres, 93% de acierto, cero cortes,
    quincenas +4,4% / +4,5%, caída máxima −13,6% (sin stop desde la entrada; ops 210 mide el stop).
  - SOL y ETH: pierden con corte a 3% (la tendencia los barre) y con corte a 5% ganan con caídas de −25/−55%. No se operan.
Qué es: no predice nada; gana en meses laterales y pierde el día que BTC se va 3% y no vuelve (ahí corta y pierde ~una banda).
Es acción diaria con pérdida acotada, no una ventaja infalible. Criterio para el libro: ≥ 30 cierres y retorno neto positivo en
dos quincenas distintas; si pierde 3 bandas seguidas se apaga sola (mode=off en el estado, una sesión la rehabilita).

Regla, cada minuto (ciclo del radar), con la última vela CERRADA de 1 min de Binance (igual que el backtest):
  centro = media de los últimos 120 cierres; dev = precio/centro − 1.
  - |dev| > KILL → cierra todo (corte por tendencia) y no abre hasta que |dev| vuelva a ≤ STEP.
  - dev ≤ −STEP y sin largo → abre largo; dev ≥ +STEP y sin corto → abre corto. Colateral LAB_GRID_COLL (US$20) a LAB_GRID_LEV (2x).
  - cada lado cierra al ganar STEP desde su entrada (toma de ganancia) o al perder ESTOP (stop desde la entrada).
  - no abre un lado que ya tenga abierto la tendencia diaria (trend.py) en la misma billetera: Jupiter funde posiciones del mismo lado.
Registro: state/desk/grid.json (panel), state/desk/grid_pos_lab.json (posiciones), radar_closed.jsonl (leg lab, reason btc_grid)
para que el motor del lab lo sume al patrimonio y el post-mortem lo juzgue. Modo: LAB_GRID=live|shadow|off.
"""
from __future__ import annotations

import json
import logging
import os
import statistics as stx
import time
from pathlib import Path

import requests

log = logging.getLogger("grid")
ST = Path("state/desk")
POS = ST / "grid_pos_lab.json"
STATE = ST / "grid.json"
CLOSED = ST / "radar_closed.jsonl"
TREND_POS = ST / "trend_pos_lab.json"
COIN = "BTC"
# ops 210–211 (31/10): CUALQUIER stop desde la entrada (1,5–8%) o tope de tiempo (12–48 h) vuelve negativa la grilla: te saca en el piso.
# El +5,9% existe solo aguantando hasta que el precio vuelve; la pérdida llega el mes que no vuelve. Por eso: sin stop de entrada,
# solo el corte de banda (3% del centro) y un stop de desastre (12%) por seguridad de liquidación.
R = {"center_n": 120, "step": 0.008, "kill": 0.03, "estop": float(os.getenv("LAB_GRID_ESTOP", "0.12")),
     "coll": float(os.getenv("LAB_GRID_COLL", "20")), "lev": float(os.getenv("LAB_GRID_LEV", "2")), "max_opens_day": 12, "halt_losses": 3}
FEE_RT = 0.0012 + 0.001   # comisión ida y vuelta + slippage estimado (para el P&L registrado; el real sale de la billetera)


def jload(p, d):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def jsave(p, o):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp"); json.dump(o, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def closes_1m(n):
    r = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": COIN + "USDT", "interval": "1m", "limit": n + 1}, timeout=15).json()
    rows = [(int(c[0]) // 1000, float(c[4])) for c in r]
    return rows[:-1]   # la última está en curso: solo velas cerradas


class GridLab:
    def __init__(self, radar):
        self.radar = radar
        self.leg = next(l for l in radar.legs if l["name"] == "lab")
        self.mode = os.getenv("LAB_GRID", "live")
        self.pos: dict = jload(POS, {}) or {}
        self.st: dict = jload(STATE, {}) or {}
        if self.st.get("mode") == "off":
            self.mode = "off"
        self.last_bar = 0
        self.opens_day: list[float] = [t for t in self.st.get("opens_day", []) if time.time() - t < 86400]
        self.loss_streak = int(self.st.get("loss_streak", 0))
        self.wait_reset = bool(self.st.get("wait_reset", False))

    # ----- ciclo -----
    def step(self):
        now = time.time()
        try:
            rows = closes_1m(R["center_n"] + 5)
        except Exception as e:  # noqa: BLE001
            log.warning("grid velas: %s", e); return
        if len(rows) < R["center_n"] or rows[-1][0] == self.last_bar:
            return
        self.last_bar = rows[-1][0]
        c = rows[-1][1]; center = stx.fmean(x[1] for x in rows[-R["center_n"]:]); dev = c / center - 1
        info = {"ts": now, "bar": self.last_bar, "px": c, "center": round(center, 2), "dev": round(dev, 5)}
        if self.mode != "off":
            try:
                self.manage(c, dev, now)
                if self.mode != "off":
                    self.maybe_open(c, dev, now)
            except Exception as e:  # noqa: BLE001
                log.exception("grid: %s", e)
        self.opens_day = [t for t in self.opens_day if now - t < 86400]
        closed = [json.loads(l) for l in CLOSED.read_text().splitlines() if l.strip()] if CLOSED.exists() else []
        mine = [r for r in closed if r.get("reason") == "btc_grid"]
        self.st = {**info, "mode": self.mode, "rules": R, "positions": self.pos, "opens_day": self.opens_day, "loss_streak": self.loss_streak,
                   "wait_reset": self.wait_reset, "closed": len(mine), "pnl_usd": round(sum(float(r.get("pnl_usd") or 0) for r in mine), 2),
                   "wins": sum(1 for r in mine if float(r.get("pnl_usd") or 0) > 0),
                   "unrealized_usd": round(sum(self._pnl(p, c) for p in self.pos.values()), 2)}
        jsave(STATE, self.st)

    @staticmethod
    def _pnl(p, price):
        d = 1 if p["side"] == "long" else -1
        return d * (price / p["entry"] - 1) * p["size_usd"]

    def _trend_side(self):
        t = jload(TREND_POS, None)
        return t.get("side") if t and t.get("symbol") == COIN else None

    def manage(self, c, dev, now):
        if abs(dev) > R["kill"] and self.pos:
            for side in list(self.pos):
                self.close(side, c, now, f"trend kill: BTC is {dev:+.1%} from its 2-hour mean (band is ±{R['kill']:.0%})")
            self.wait_reset = True
            return
        if self.wait_reset and abs(dev) <= R["step"]:
            self.wait_reset = False
        for side in list(self.pos):
            p = self.pos[side]; d = 1 if side == "long" else -1
            r = d * (c / p["entry"] - 1)
            p.update({"mark": c, "ret_px": round(r, 4), "pnl_usd_est": round(r * p["size_usd"], 2), "age_h": round((now - p["ts"]) / 3600, 2)})
            if r >= R["step"]:
                self.close(side, c, now, f"grid take-profit: +{R['step']:.1%} from entry")
            elif R["estop"] and r <= -R["estop"]:
                self.close(side, c, now, f"entry stop: {R['estop']:.1%} against the entry")
        if self.pos:
            jsave(POS, self.pos)

    def maybe_open(self, c, dev, now):
        if self.wait_reset or abs(dev) > R["kill"] or len(self.opens_day) >= R["max_opens_day"]:
            return
        want = "long" if dev <= -R["step"] else "short" if dev >= R["step"] else None
        if not want or want in self.pos:
            return
        if self._trend_side() == want:
            return   # la tendencia diaria ya tiene ese lado en esta billetera
        self.open(want, c, dev, now)

    # ----- órdenes -----
    def open(self, side, price, dev, now):
        coll, lev = R["coll"], R["lev"]
        rec = {"ts": now, "leg": "lab", "plan": "lab", "symbol": COIN, "side": side, "entry": price, "collateral_usd": coll, "lev": lev,
               "size_usd": round(coll * lev, 2), "mode": self.mode, "dev": round(dev, 5), "pubkey": None, "reason": "btc_grid"}
        if self.mode == "live":
            try:
                r = self.radar.perps(self.leg).open(COIN, side, coll, lev, dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                log.error("grid: no abrió %s: %s", side, r.get("error"))
                self.radar_log("grid_open_failed", side=side, error=str(r.get("error"))[:300]); self.opens_day.append(now)
                return
            rec.update({"pubkey": r.get("position_pubkey"), "sig": r.get("sig")})
            try:
                live = [q for q in self.radar.perps(self.leg).positions() if q.get("pubkey") == rec["pubkey"]]
                if live and live[0].get("entry"): rec["entry"] = float(live[0]["entry"])
            except Exception:  # noqa: BLE001
                pass
        self.pos[side] = rec; jsave(POS, self.pos); self.opens_day.append(now)
        self.radar_log("grid_open", **rec)
        self.note(f"Lab grid: {side} BTC at ${rec['entry']:,.0f}",
                  f"BTC is {dev:+.2%} from its 2-hour average. The grid {('buys' if side == 'long' else 'sells')} the dip and takes profit when price "
                  f"comes back {R['step']:.1%}; it stops out {R['estop']:.1%} against the entry, or closes everything if BTC leaves the ±{R['kill']:.0%} band. "
                  f"${coll:.0f} collateral at {lev:.0f}x on Jupiter Perps. This test sells volatility: it does not predict direction, it gets paid for "
                  f"absorbing swings inside a range (backtest 30 d: +5.9% at 1x, 93% wins, 15 trades).")

    def close(self, side, price, now, why):
        p = self.pos.get(side)
        if not p:
            return
        if p.get("mode") == "live" and p.get("pubkey"):
            try:
                r = self.radar.perps(self.leg).close(p["pubkey"], dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                p["close_attempts"] = p.get("close_attempts", 0) + 1; jsave(POS, self.pos)
                self.radar_log("grid_close_failed", side=side, error=str(r.get("error"))[:300])
                if p["close_attempts"] < 5:
                    return
        d = 1 if side == "long" else -1
        ret = d * (price / p["entry"] - 1); pnl = ret * p["size_usd"] - p["size_usd"] * FEE_RT
        row = {"ts": now, "ts_open": p["ts"], "leg": "lab", "symbol": COIN, "side": side, "entry": p["entry"], "exit": price,
               "collateral_usd": p["collateral_usd"], "size_usd": p["size_usd"], "ret_px": round(ret, 4), "pnl_usd": round(pnl, 2),
               "hold_h": round((now - p["ts"]) / 3600, 2), "why": why, "mode": p.get("mode"), "reason": "btc_grid"}
        with open(CLOSED, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.radar_log("grid_close", **row)
        self.pos.pop(side, None); jsave(POS, self.pos)
        self.loss_streak = self.loss_streak + 1 if pnl < 0 else 0
        self.note(f"Lab grid: {side} BTC closed ({'+' if pnl >= 0 else ''}${pnl:.2f})", f"Closed: {why}. Entry ${p['entry']:,.0f}, exit ${price:,.0f}, about ${pnl:+.2f}.")
        if self.loss_streak >= R["halt_losses"]:
            self.mode = "off"
            self.radar_log("grid_halt", losses=self.loss_streak)
            self.note("Lab grid paused", f"{self.loss_streak} losing trades in a row: the grid switches itself off until a review re-enables it.")

    @staticmethod
    def radar_log(kind, **kw):
        with open(ST / "radar_log.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, **kw}, ensure_ascii=False) + "\n")

    @staticmethod
    def note(title, text):
        d = Path("state/plan_lab/auto")
        did = f"auto-lab-grid-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
        jsave(d / f"{did}.json", {"id": did, "title": title, "journal": text, "orders": [], "auto": True})
