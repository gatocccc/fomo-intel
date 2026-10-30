"""Tendencia diaria en majors con cortos en Jupiter Perps — prueba real del laboratorio (30/10/2026).

Origen: Gastón pidió "agarrar las subidas y las bajadas en las majors". Backtest `fomo_intel/experiments/majors_bt.py`
(8 mercados, 2020–2026, costos 0,10%/rotación y funding 10%/año para largos; diseño 2020–23, prueba 2024–26, control al azar):
- Señales de HORAS (4 h, rebotes, cascadas): pierden fuera de muestra. No se operan.
- Tendencia DIARIA (momentum 10–90 días, EMA 20–100, rupturas 20–55): todas positivas en la prueba, en 5–8 de 8 mercados,
  mejor que comprar y mantener en riesgo (caída máx. −38% vs −71%). Pero t ≈ 0,6–1,7: no llegan al umbral t ≥ 2. Ventaja probable,
  no demostrada → se prueba en real con el lab, chico.
- El conjunto largo/corto (promedio de 10 señales) en ETH: prueba Sharpe +0,67; en 2026 (año bajista) +15% vs −14% solo largo.

Regla (sin optimizar: el conjunto promedia 10 señales estándar, no se eligió el mejor parámetro):
  señal = promedio de [momentum 10/20/30/60/90 d, precio vs EMA 20/50/100, ruptura 20/55] ∈ [−1, +1], al cierre diario.
  - señal ≤ −0,5 → corto (en el mercado más bajista de BTC/ETH); se cierra si la señal sube a > −0,2.
  - señal ≥ +0,5 → largo; se cierra si baja a < +0,2.   (largo y corto con la misma lógica: el libro ya compra spot por su cuenta)
  - apalancamiento = objetivo de vol 60%/año ÷ vol de 30 días, entre 1x y 2x. Colateral fijo chico (LAB_TREND_COLL, US$10).
  - stop duro: el precio va 8% en contra de la entrada; tope 14 días (se re-evalúa abriendo de nuevo si la señal sigue).
Se revisa una vez por hora; la señal solo cambia con el cierre diario (00:00 UTC). Cada operación se registra en radar_closed.jsonl
(leg "lab", reason "majors_trend") para que el motor del lab la sume al patrimonio y el post-mortem la juzgue.
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics as stx
import time
from pathlib import Path

import requests

log = logging.getLogger("trend")
HL = "https://api.hyperliquid.xyz/info"
ST = Path("state/desk")
POS = ST / "trend_pos_lab.json"
STATE = ST / "trend.json"
CLOSED = ST / "radar_closed.jsonl"
COINS = ("BTC", "ETH")
R = {"enter": 0.5, "exit": 0.2, "vt": 0.60, "lev_min": 1.0, "lev_max": 2.0, "stop": 0.08, "max_d": 14, "coll": float(os.getenv("LAB_TREND_COLL", "10"))}


def jload(p, d):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def jsave(p, o):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp"); json.dump(o, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def daily(coin, days=200):
    end = int(time.time() * 1000)
    r = requests.post(HL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": end - days * 86400000, "endTime": end}}, timeout=20)
    rows = r.json() if r.ok else []
    # solo velas CERRADAS (la de hoy está en curso)
    today = int(time.time() // 86400) * 86400
    return [(int(c["t"]) // 1000, float(c["h"]), float(c["l"]), float(c["c"])) for c in rows if int(c["t"]) // 1000 < today]


def ema(xs, n):
    k = 2 / (n + 1); e = None; out = []
    for x in xs:
        e = x if e is None else e + k * (x - e); out.append(e)
    return out


def signal(rows):
    """Promedio de 10 señales de tendencia estándar al último cierre. Devuelve (señal, vol anual 30 d, detalle)."""
    h = [r[1] for r in rows]; l = [r[2] for r in rows]; c = [r[3] for r in rows]; i = len(c) - 1
    if i < 110:
        return None, None, {}
    parts = {}
    for n in (10, 20, 30, 60, 90):
        parts[f"mom{n}"] = 1.0 if c[i] > c[i - n] else -1.0
    for n in (20, 50, 100):
        parts[f"ema{n}"] = 1.0 if c[i] > ema(c, n)[i] else -1.0
    for n in (20, 55):   # ruptura tipo tortuga con salida en n/2 (estado recorrido desde el inicio de la serie)
        pos = 0.0; m = n // 2
        for j in range(n, i + 1):
            hi, lo, xhi, xlo = max(h[j - n:j]), min(l[j - n:j]), max(h[j - m:j]), min(l[j - m:j])
            if pos == 0:
                pos = 1.0 if c[j] > hi else (-1.0 if c[j] < lo else 0.0)
            elif pos > 0 and c[j] < xlo: pos = -1.0 if c[j] < lo else 0.0
            elif pos < 0 and c[j] > xhi: pos = 1.0 if c[j] > hi else 0.0
        parts[f"don{n}"] = pos
    rets = [c[j] / c[j - 1] - 1 for j in range(i - 29, i + 1)]
    vol = stx.pstdev(rets) * math.sqrt(365)
    return round(stx.mean(parts.values()), 2), round(vol, 3), parts


class TrendLab:
    def __init__(self, radar):
        self.radar = radar            # reusa el cliente de perps y la billetera del lab
        self.leg = next(l for l in radar.legs if l["name"] == "lab")
        self.mode = os.getenv("LAB_TREND", "live")
        self.pos = jload(POS, None)
        self.last = 0.0

    def step(self):
        now = time.time()
        if now - self.last < 3600 and not (self.pos and now - self.last > 300):
            return
        self.last = now
        sig = {}
        for coin in COINS:
            try:
                s, v, parts = signal(daily(coin))
            except Exception as e:  # noqa: BLE001
                log.warning("trend %s: %s", coin, e); continue
            if s is not None:
                sig[coin] = {"signal": s, "vol": v, "parts": parts}
        px = {}
        try:
            cs = requests.post(HL, json={"type": "allMids"}, timeout=15).json()
            px = {k: float(cs[k]) for k in COINS if k in cs}
        except Exception as e:  # noqa: BLE001
            log.warning("trend precios: %s", e)
        st = {"ts": now, "mode": self.mode, "signals": sig, "px": px, "rules": R, "position": self.pos}
        if self.pos:
            self.manage(sig, px, now)
        elif sig and px and self.mode != "off":
            # el mercado con la señal más extrema; empate → ETH (mejor en la prueba)
            coin = max(sig, key=lambda k: (abs(sig[k]["signal"]), k == "ETH"))
            s = sig[coin]["signal"]
            if abs(s) >= R["enter"]:
                self.open(coin, "short" if s < 0 else "long", sig[coin], px[coin], now)
        st["position"] = self.pos
        jsave(STATE, st)

    def open(self, coin, side, sg, price, now):
        lev = round(max(R["lev_min"], min(R["lev_max"], R["vt"] / max(sg["vol"], 1e-6))), 2)
        coll = R["coll"]
        rec = {"ts": now, "leg": "lab", "plan": "lab", "symbol": coin, "side": side, "entry": price, "collateral_usd": coll, "lev": lev,
               "size_usd": round(coll * lev, 2), "mode": self.mode, "signal": sg["signal"], "vol": sg["vol"], "parts": sg["parts"], "pubkey": None, "reason": "majors_trend"}
        if self.mode == "live":
            try:
                r = self.radar.perps(self.leg).open(coin, side, coll, lev, dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                log.error("trend: no abrió %s %s: %s", side, coin, r.get("error"))
                self.radar_log("trend_open_failed", coin=coin, side=side, error=str(r.get("error"))[:300]); return
            rec.update({"pubkey": r.get("position_pubkey"), "sig": r.get("sig")})
            try:
                live = [q for q in self.radar.perps(self.leg).positions() if q.get("pubkey") == rec["pubkey"]]
                if live and live[0].get("entry"): rec["entry"] = float(live[0]["entry"])
            except Exception:  # noqa: BLE001
                pass
        self.pos = rec; jsave(POS, rec); self.radar_log("trend_open", **{k: v for k, v in rec.items() if k != "parts"})
        self.note(f"Lab test: daily-trend {side} on {coin}",
                  f"The daily trend signal for {coin} is {sg['signal']:+.1f} (average of 10 standard trend rules: momentum 10–90 days, price vs 20/50/100-day "
                  f"averages, 20/55-day breakouts). Lab opens a {side} on Jupiter Perps: ${coll:.0f} collateral at {lev:.2f}x (sized to 60% annual volatility), "
                  f"entry ${rec['entry']:,.2f}. Exit when the signal fades past ±{R['exit']}, a hard stop {R['stop']:.0%} against the entry, or {R['max_d']} days. "
                  f"Why a test and not the book: in the 2024–26 backtest these rules beat buy-and-hold on risk in most markets, but the edge is not yet "
                  f"statistically proven (t ≈ 0.6–1.7). Against: trend rules lose in choppy markets, and shorting after a 16% monthly drop can catch the bounce.")

    def manage(self, sig, px, now):
        p = self.pos; coin = p["symbol"]; price = px.get(coin)
        if not price:
            return
        d = 1 if p["side"] == "long" else -1
        ret = d * (price / p["entry"] - 1)
        p.update({"mark": price, "ret_px": round(ret, 4), "pnl_usd_est": round(ret * p["size_usd"], 2), "age_d": round((now - p["ts"]) / 86400, 2)})
        s = (sig.get(coin) or {}).get("signal")
        why = None
        if ret <= -R["stop"]: why = f"hard stop: {coin} moved {R['stop']:.0%} against the entry"
        elif s is not None and d * s < R["exit"]: why = f"signal faded ({s:+.1f})"
        elif now - p["ts"] > R["max_d"] * 86400: why = f"time stop ({R['max_d']} days)"
        if why:
            self.close(why, price, now)
        else:
            jsave(POS, p)

    def close(self, why, price, now):
        p = self.pos
        if p.get("mode") == "live" and p.get("pubkey"):
            try:
                r = self.radar.perps(self.leg).close(p["pubkey"], dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                p["close_attempts"] = p.get("close_attempts", 0) + 1; jsave(POS, p)
                self.radar_log("trend_close_failed", error=str(r.get("error"))[:300])
                if p["close_attempts"] < 5:
                    return
        d = 1 if p["side"] == "long" else -1
        ret = d * (price / p["entry"] - 1); pnl = ret * p["size_usd"] - p["size_usd"] * 0.0012 * 2
        row = {"ts": now, "ts_open": p["ts"], "leg": "lab", "symbol": p["symbol"], "side": p["side"], "entry": p["entry"], "exit": price,
               "collateral_usd": p["collateral_usd"], "size_usd": p["size_usd"], "ret_px": round(ret, 4), "pnl_usd": round(pnl, 2),
               "hold_h": round((now - p["ts"]) / 3600, 2), "why": why, "mode": p.get("mode"), "reason": "majors_trend"}
        with open(CLOSED, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.radar_log("trend_close", **row)
        self.note(f"Lab test: {p['side']} on {p['symbol']} closed",
                  f"Closed: {why}. Entry ${p['entry']:,.2f}, exit ${price:,.2f}, result about ${pnl:+.2f} on ${p['collateral_usd']:.0f} collateral.")
        self.pos = None
        if POS.exists(): POS.unlink()

    @staticmethod
    def radar_log(kind, **kw):
        with open(ST / "radar_log.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, **kw}, ensure_ascii=False) + "\n")

    @staticmethod
    def note(title, text):
        d = Path("state/plan_lab/auto")
        did = f"auto-lab-trend-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
        jsave(d / f"{did}.json", {"id": did, "title": title, "journal": text, "orders": [], "auto": True})
