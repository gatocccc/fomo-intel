"""Perps de Hyperliquid: ¿qué hacen los vaults que ganan? (31/10/2026)

Pregunta (Gastón): AceVault gana shorteando altcoins débiles; Growi sigue tendencia; Amber Ridge va largo majors
y corto altcoins. ¿Alguna de esas estructuras tiene ventaja medible con costos reales, fuera de muestra?

Datos: velas diarias de TODO el universo de Hyperliquid (incluidos los deslistados, sin sesgo de supervivencia).
Protocolo: diseño hasta SPLIT, prueba después (nunca vista al elegir). Señal con cierre del día t, operación al cierre
de t+DELAY (DELAY=1 por defecto: un día de demora, conservador). Costos: comisión 0,045% + slippage por liquidez,
funding conservador (los largos pagan 10%/año, los cortos no cobran nada). Control: carteras al azar del mismo tamaño.

Uso (servidor):  python3 -m fomo_intel.experiments.xsec_bt pull
                 python3 -m fomo_intel.experiments.xsec_bt analyze
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
import time
from pathlib import Path

import requests

API = "https://api.hyperliquid.xyz/info"
DIR = Path("data/xsec")
OUT = Path("state/research/xsec.json")
DAY = 86400
SPLIT = "2025-07-01"
FEE = 0.00045
LONG_FUND = 0.10 / 365


def post(body):
    for i in range(5):
        try:
            r = requests.post(API, json=body, timeout=30)
            if r.status_code == 429:
                time.sleep(3 + 3 * i); continue
            r.raise_for_status(); return r.json()
        except Exception:
            time.sleep(2 + 2 * i)
    return None


def pull():
    DIR.mkdir(parents=True, exist_ok=True)
    meta = post({"type": "meta"})
    uni = meta["universe"]
    json.dump(uni, open(DIR / "universe.json", "w"))
    t_end = int(time.time() * 1000); t0 = int(time.mktime(time.strptime("2023-01-01", "%Y-%m-%d")) * 1000)
    n = 0
    for u in uni:
        c = u["name"]
        f = DIR / f"{c.replace('/', '_')}.json"
        if f.exists() and time.time() - f.stat().st_mtime < 6 * 3600:
            continue
        d = post({"type": "candleSnapshot", "req": {"coin": c, "interval": "1d", "startTime": t0, "endTime": t_end}})
        if d:
            json.dump([[int(x["t"]) // 1000, float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x["v"])] for x in d], open(f, "w"))
            n += 1
        time.sleep(0.25)
    print("universo", len(uni), "deslistados", sum(1 for u in uni if u.get("isDelisted")), "descargados", n)


# ---------------------------------------------------------------- datos
def load():
    uni = json.load(open(DIR / "universe.json"))
    px, vol = {}, {}
    for u in uni:
        f = DIR / f"{u['name'].replace('/', '_')}.json"
        if not f.exists():
            continue
        for t, o, h, l, c, v in json.load(open(f)):
            d = t // DAY
            px.setdefault(u["name"], {})[d] = c
            vol.setdefault(u["name"], {})[d] = v * c  # volumen en USD aprox.
    days = sorted({d for s in px.values() for d in s})
    return px, vol, days


def slip(usd_vol):
    return 0.0005 if usd_vol >= 50e6 else 0.0015 if usd_vol >= 10e6 else 0.003


# ---------------------------------------------------------------- simulador
def simulate(px, vol, days, signal, rebalance=1, delay=1, min_vol=3e6, min_age=30, gross=1.0, random_ctrl=None):
    """signal(px, d, eligible) -> {coin: weight} (suma |w| <= 1 antes de 'gross'). Devuelve serie diaria de retorno neto."""
    coins = list(px)
    first = {c: min(px[c]) for c in coins}
    rets, w_now, pending = [], {}, []
    rng = random.Random(random_ctrl) if random_ctrl is not None else None
    for i, d in enumerate(days[:-1]):
        # elegibles el día d (memo)
        key = (d, min_vol, min_age)
        if key in _ELIG:
            elig = _ELIG[key]
        else:
            elig = _elig(px, vol, coins, first, d, min_vol, min_age); _ELIG[key] = elig
        if i % rebalance == 0 and len(elig) >= 10:
            w = signal(px, d, elig)
            if rng is not None and w:
                # control: mismas magnitudes de peso, monedas al azar entre las elegibles
                vals = list(w.values()); pick = rng.sample(elig, len(vals)); w = dict(zip(pick, vals))
            pending.append((i + delay, {c: x * gross for c, x in w.items()}))
        cost = 0.0
        while pending and pending[0][0] <= i:
            _, w_new = pending.pop(0)
            for c in set(w_now) | set(w_new):
                dw = abs(w_new.get(c, 0) - w_now.get(c, 0))
                if dw:
                    cost += dw * (FEE + slip(sum(vol[c].get(d - k, 0) for k in range(7)) / 7))
            w_now = w_new
        d1 = days[i + 1]
        r = 0.0
        for c, w in list(w_now.items()):
            p0, p1 = px[c].get(d), px[c].get(d1)
            if p0 and p1:
                r += w * (p1 / p0 - 1)
                if w > 0:
                    r -= w * LONG_FUND
            elif p0 and not p1:   # deslistado: se liquida al último precio (ya contado)
                w_now.pop(c)
        rets.append((d1, r - cost))
    return rets


def _elig(px, vol, coins, first, d, min_vol, min_age):
    out = []
    for c in coins:
        p = px[c]
        if d not in p or d - first[c] < min_age:
            continue
        if sum(vol[c].get(d - k, 0) for k in range(7)) / 7 < min_vol:
            continue
        out.append(c)
    return out


def mom(px, c, d, L):
    p0, p1 = px[c].get(d - L), px[c].get(d)
    return p1 / p0 - 1 if p0 and p1 else None


_V20 = {}
_ELIG = {}


def vol20(px, c, d):
    k = (c, d)
    if k in _V20:
        return _V20[k]
    _V20[k] = _vol20(px, c, d)
    return _V20[k]


def _vol20(px, c, d):
    r = []
    for k in range(20):
        a, b = px[c].get(d - k - 1), px[c].get(d - k)
        if a and b:
            r.append(b / a - 1)
    return st.pstdev(r) if len(r) >= 10 else None


def ivw(coins, px, d):
    iv = {}
    for c in coins:
        v = vol20(px, c, d)
        if v and v > 0:
            iv[c] = 1 / v
    s = sum(iv.values())
    return {c: x / s for c, x in iv.items()} if s else {}


def xs_mom(L, q, sign=1):
    def f(px, d, elig):
        sc = [(mom(px, c, d, L), c) for c in elig]
        sc = sorted([x for x in sc if x[0] is not None])
        n = max(2, int(len(sc) * q))
        lo, hi = [c for _, c in sc[:n]], [c for _, c in sc[-n:]]
        L_, S_ = (hi, lo) if sign > 0 else (lo, hi)
        w = {c: 0.5 * x for c, x in ivw(L_, px, d).items()}
        for c, x in ivw(S_, px, d).items():
            w[c] = w.get(c, 0) - 0.5 * x
        return w
    return f


def short_weak(L, q):
    def f(px, d, elig):
        sc = sorted([x for x in ((mom(px, c, d, L), c) for c in elig) if x[0] is not None])
        n = max(2, int(len(sc) * q))
        return {c: -x for c, x in ivw([c for _, c in sc[:n]], px, d).items()}
    return f


def majors_vs_weak(L, q):
    def f(px, d, elig):
        sc = sorted([x for x in ((mom(px, c, d, L), c) for c in elig if c not in ("BTC", "ETH", "SOL")) if x[0] is not None])
        n = max(2, int(len(sc) * q))
        w = {c: 0.5 / 3 for c in ("BTC", "ETH", "SOL") if c in elig}
        for c, x in ivw([c for _, c in sc[:n]], px, d).items():
            w[c] = w.get(c, 0) - 0.5 * x
        return w
    return f


def ts_trend(L):
    def f(px, d, elig):
        sgn = {c: (1 if m > 0 else -1) for c in elig if (m := mom(px, c, d, L)) is not None}
        iv = ivw(list(sgn), px, d)
        return {c: sgn[c] * x for c, x in iv.items()}
    return f


def stats(rets):
    if len(rets) < 30:
        return None
    r = [x for _, x in rets]
    m, s = st.mean(r), st.pstdev(r) or 1e-12
    eq, peak, dd = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x; peak = max(peak, eq); dd = min(dd, eq / peak - 1)
    months = {}
    for d, x in rets:
        k = time.strftime("%Y-%m", time.gmtime(d * DAY)); months[k] = months.get(k, 0) + x
    return {"n": len(r), "ann": round((eq ** (365 / len(r)) - 1) * 100, 1), "sharpe": round(m / s * math.sqrt(365), 2),
            "t": round(m / s * math.sqrt(len(r)), 2), "maxdd": round(dd * 100, 1),
            "pos_months": f"{sum(v > 0 for v in months.values())}/{len(months)}"}


def analyze():
    px, vol, days = load()
    split = int(time.mktime(time.strptime(SPLIT, "%Y-%m-%d"))) // DAY
    print("monedas", len(px), "días", len(days), time.strftime("%Y-%m-%d", time.gmtime(days[0] * DAY)), "→", time.strftime("%Y-%m-%d", time.gmtime(days[-1] * DAY)))
    grid = []
    for L in (3, 7, 14, 30, 60):
        for R in (1, 3, 7):
            for q in (0.2, 0.3):
                grid.append((f"xs_mom L{L} R{R} q{q}", xs_mom(L, q), R))
    for L in (1, 3):
        grid.append((f"xs_reversal L{L} R1 q0.2", xs_mom(L, 0.2, -1), 1))
    for L in (7, 14, 30):
        for R in (1, 7):
            grid.append((f"short_weak L{L} R{R} q0.2", short_weak(L, 0.2), R))
            grid.append((f"majors_vs_weak L{L} R{R} q0.2", majors_vs_weak(L, 0.2), R))
    for L in (14, 30, 60):
        for R in (1, 7):
            grid.append((f"ts_trend L{L} R{R}", ts_trend(L), R))
    res = []
    for name, sig, R in grid:
        rets = simulate(px, vol, days, sig, rebalance=R)
        dz = [x for x in rets if x[0] < split]; tz = [x for x in rets if x[0] >= split]
        row = {"name": name, "design": stats(dz), "test": stats(tz), "all": stats(rets)}
        res.append(row)
        print(f"{name:32s} diseño {row['design']}  prueba {row['test']}", flush=True)
    # control al azar para los 5 mejores del diseño
    best = sorted([r for r in res if r["design"]], key=lambda r: -r["design"]["sharpe"])[:5]
    for b in best:
        name = b["name"]; sig, R = next((g[1], g[2]) for g in grid if g[0] == name)
        ctrl = []
        for k in range(30):
            rets = simulate(px, vol, days, sig, rebalance=R, random_ctrl=k)
            s = stats([x for x in rets if x[0] >= split])
            if s: ctrl.append(s["sharpe"])
        ctrl.sort()
        b["ctrl_test_sharpe_p50_p95"] = [ctrl[len(ctrl) // 2], ctrl[int(len(ctrl) * 0.95) - 1]] if ctrl else None
        # robustez: sin demora y con 2 días de demora
        b["delay0_test"] = stats([x for x in simulate(px, vol, days, sig, rebalance=R, delay=0) if x[0] >= split])
        b["delay2_test"] = stats([x for x in simulate(px, vol, days, sig, rebalance=R, delay=2) if x[0] >= split])
        print("CONTROL", name, b["ctrl_test_sharpe_p50_p95"], "delay0", b["delay0_test"], "delay2", b["delay2_test"], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"split": SPLIT, "coins": len(px), "results": res, "best_design": [b["name"] for b in best]}, open(OUT, "w"), indent=1)
    print("OK", OUT)


if __name__ == "__main__":
    {"pull": pull, "analyze": analyze}[sys.argv[1]]()
