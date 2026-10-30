"""Backtest de estrategias de majors (30/10/2026, pedido de Gastón: "agarrar las subidas y las bajadas en las majors").

Por qué otro backtest: el de perps del 28/10 (perps_bt.py) usó 90 días de velas de 1 h y señales de horas (cascadas, rupturas,
funding). La evidencia publicada sobre cripto dice que la ventaja más robusta está en otro horizonte: momentum de series de
tiempo / seguimiento de tendencia de DÍAS a SEMANAS (Liu & Tsyvinski 2021; Hurst-Ooi-Pedersen para futuros en general), con
tamaño ajustado a la volatilidad. Eso no se puede medir con 90 días: hacen falta años.

Protocolo (el mismo espíritu del 25/10):
- Datos: velas diarias y de 4 h de Binance 2020-01 → hoy (8 mercados: BTC ETH SOL BNB XRP DOGE AVAX LINK).
- Señal con el cierre de la vela t; la posición rige desde la vela t+1 (sin mirar el futuro).
- Costos: 0,10% por unidad de rotación (comisión 0,045–0,06% + slippage) y funding de perps: los largos pagan 10%/año, los
  cortos no cobran nada (conservador: históricamente el funding positivo les paga a los cortos).
- Diseño 2020-01-01 → 2023-12-31 (se elige el parámetro); prueba 2024-01-01 → hoy (nunca vista al elegir).
- Control al azar: posiciones con el mismo largo de tramos y la misma exposición, en momentos al azar (200 repeticiones).
- Criterio para operar en real: en la PRUEBA, cartera de los 8 mercados con Sharpe ≥ 0,8, t ≥ 2, mejor que el 95% del azar,
  diseño positivo, y > 0 en al menos 5 de 8 mercados.

Uso: python -m fomo_intel.experiments.majors_bt data.json   (data.json = salida de scripts/pull_majors.py)
"""
from __future__ import annotations

import json
import math
import random
import statistics as stx
import sys
import time

COST = 0.0010
FUND_LONG_Y = 0.10
SPLIT = time.mktime((2024, 1, 1, 0, 0, 0, 0, 0, 0))
START = time.mktime((2020, 1, 1, 0, 0, 0, 0, 0, 0))
ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK"]


def ema(xs, n):
    k = 2 / (n + 1); out = []; e = None
    for x in xs:
        e = x if e is None else e + k * (x - e); out.append(e)
    return out


def rets(c):
    return [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, len(c))]


def rvol(r, i, w):   # versión lenta, solo para dip/rip
    seg = r[max(1, i - w + 1): i + 1]
    return stx.pstdev(seg) if len(seg) > 5 else None


# ---------------------------------------------------------------- señales: devuelven la posición deseada al cierre de cada vela
def sig_tsmom(c, h, l, n, mode):
    p = [0.0] * len(c)
    for i in range(n, len(c)):
        s = 1.0 if c[i] > c[i - n] else -1.0
        p[i] = s if mode == "ls" else max(0.0, s)
    return p


def sig_ema(c, h, l, n, mode):
    e = ema(c, n); p = [0.0] * len(c)
    for i in range(n, len(c)):
        s = 1.0 if c[i] > e[i] else -1.0
        p[i] = s if mode == "ls" else max(0.0, s)
    return p


def sig_ema_x(c, h, l, n, mode):         # cruce de medias rápida/lenta (n = lenta, rápida = n/4)
    f, s_ = ema(c, max(2, n // 4)), ema(c, n); p = [0.0] * len(c)
    for i in range(n, len(c)):
        s = 1.0 if f[i] > s_[i] else -1.0
        p[i] = s if mode == "ls" else max(0.0, s)
    return p


def sig_donchian(c, h, l, n, mode):       # tortuga: entra en máximo de n velas, sale en mínimo de n/2 (y espejo para cortos)
    p = [0.0] * len(c); pos = 0.0; m = max(2, n // 2)
    for i in range(n, len(c)):
        hi, lo = max(h[i - n:i]), min(l[i - n:i])
        xhi, xlo = max(h[i - m:i]), min(l[i - m:i])
        if pos == 0:
            if c[i] > hi: pos = 1.0
            elif c[i] < lo and mode == "ls": pos = -1.0
        elif pos > 0 and c[i] < xlo: pos = -1.0 if (mode == "ls" and c[i] < lo) else 0.0
        elif pos < 0 and c[i] > xhi: pos = 1.0 if c[i] > hi else 0.0
        p[i] = pos
    return p


def sig_dip(c, h, l, n, mode):            # rebote dentro de tendencia: sobre EMA 100, cae > n/10 σ en 3 velas → largo 5 velas
    e = ema(c, 100); vs = vol_series(c); p = [0.0] * len(c); hold = 0
    k = n / 10
    for i in range(101, len(c)):
        v = vs[i]
        if hold > 0: hold -= 1; p[i] = 1.0; continue
        if v and c[i] > e[i] * 0.97 and c[i] / c[i - 3] - 1 < -k * v * math.sqrt(3):
            hold = 4; p[i] = 1.0
    return p


def sig_rip(c, h, l, n, mode):            # espejo: bajo la EMA 100, rebota > n/10 σ en 3 velas → corto 5 velas
    e = ema(c, 100); vs = vol_series(c); p = [0.0] * len(c); hold = 0
    k = n / 10
    for i in range(101, len(c)):
        v = vs[i]
        if hold > 0: hold -= 1; p[i] = -1.0; continue
        if v and c[i] < e[i] * 1.03 and c[i] / c[i - 3] - 1 > k * v * math.sqrt(3):
            hold = 4; p[i] = -1.0
    return p


SIGNALS = {
    "tsmom": (sig_tsmom, [5, 10, 20, 30, 60, 90]),
    "ema": (sig_ema, [10, 20, 50, 100]),
    "ema_cross": (sig_ema_x, [20, 40, 80, 120]),
    "donchian": (sig_donchian, [10, 20, 55]),
    "dip_buy": (sig_dip, [10, 15, 20]),
    "rip_short": (sig_rip, [10, 15, 20]),
}


# ---------------------------------------------------------------- simulación
_VOL = {}


def vol_series(c, w=30):
    """Desvío de los retornos de las últimas w velas, para cada vela (cacheado por serie)."""
    key = (id(c), len(c), c[0], c[-1], c[len(c) // 2], w)
    if key in _VOL: return _VOL[key]
    r = rets(c); out = [None] * len(c); s1 = s2 = 0.0; q = []
    for i in range(1, len(c)):
        q.append(r[i]); s1 += r[i]; s2 += r[i] * r[i]
        if len(q) > w: x = q.pop(0); s1 -= x; s2 -= x * x
        if len(q) > 5:
            m = s1 / len(q); out[i] = math.sqrt(max(0.0, s2 / len(q) - m * m))
    _VOL[key] = out
    return out


def simulate(ts, c, pos, bars_y, vt=None):
    """Retornos por vela de la estrategia. pos[i] decidido al cierre de i rige en i+1. vt = objetivo de vol anual (tamaño 1/vol, tope 2x)."""
    r = rets(c); out = []; prev = 0.0; vs = vol_series(c) if vt else None; sy = math.sqrt(bars_y); fl = FUND_LONG_Y / bars_y
    for i in range(1, len(c)):
        w = pos[i - 1]
        if vt and w:
            v = vs[i - 1]
            w = w * min(2.0, vt / (v * sy)) if v else 0.0
        cost = abs(w - prev) * COST
        out.append((ts[i], w * r[i] - cost - (fl * w if w > 0 else 0.0), w))
        prev = w
    return out


def perf(rows, bars_y):
    x = [a for _, a, _ in rows]
    if len(x) < 30: return {"n": len(x)}
    m, s = stx.mean(x), stx.pstdev(x)
    eq = 1.0; pk = 1.0; dd = 0.0
    for a in x:
        eq *= 1 + a; pk = max(pk, eq); dd = min(dd, eq / pk - 1)
    yrs = len(x) / bars_y
    return {"n": len(x), "cagr": eq ** (1 / yrs) - 1 if eq > 0 else -1, "sharpe": (m / s * math.sqrt(bars_y)) if s else 0,
            "t": (m / s * math.sqrt(len(x))) if s else 0, "maxdd": dd, "tot": eq - 1,
            "expo": stx.mean(abs(w) for _, _, w in rows)}


def split(rows):
    return [r for r in rows if START <= r[0] < SPLIT], [r for r in rows if r[0] >= SPLIT]


def portfolio(per_asset):
    """Cartera de igual peso: promedio de los retornos por vela de los mercados que tienen dato ese día."""
    by_t = {}
    for rows in per_asset.values():
        for t, a, w in rows:
            by_t.setdefault(t, []).append((a, w))
    return [(t, stx.mean(a for a, _ in v), stx.mean(abs(w) for _, w in v)) for t, v in sorted(by_t.items())]


def random_control(series, fn, param, mode, bars_y, vt, reps=200):
    """Misma estrategia, pero la serie de posiciones se corre un desfase al azar (rotación circular): mismos tramos y exposición,
    otro momento. Si la estrategia no le gana a eso, su resultado es suerte de calendario."""
    sh = []; base = {}
    for a, (ts, o, h, l, c) in series.items():
        p = fn(c, h, l, param, mode)
        test_idx = [i for i, t in enumerate(ts) if t >= SPLIT]
        if test_idx: i0 = test_idx[0]; base[a] = (ts[i0 - 1:], c[i0 - 1:], p[i0 - 1:])
    for k in range(reps):
        rnd = random.Random(7 + k); pa = {}
        for a, (ts, c, p) in base.items():
            first, seg = p[:1], p[1:]; d = rnd.randrange(30, max(31, len(seg) - 30))
            pa[a] = simulate(ts, c, first + seg[d:] + seg[:d], bars_y, vt)
        pf = perf(portfolio(pa), bars_y)
        sh.append(pf.get("sharpe", 0))
    sh.sort()
    return {"p50": sh[len(sh) // 2], "p95": sh[int(len(sh) * 0.95)]}


def load(path, tf):
    D = json.load(open(path)); series = {}
    for a in ASSETS:
        rows = D.get(f"{a}USDT_{tf}") or []
        rows = [r for r in rows if r[0] >= START - 200 * 86400]
        if len(rows) < 300: continue
        ts, o, h, l, c = ([r[k] for r in rows] for k in range(5))
        series[a] = (ts, o, h, l, c)
    return series


def run(path, tf="1d", vt=0.6):
    bars_y = 365 if tf == "1d" else 365 * 6
    series = load(path, tf); results = []
    scale = 1 if tf == "1d" else 6
    print(f"\n######## velas {tf} · {len(series)} mercados · vol objetivo {vt or 'sin'} · costo {COST:.2%}/rotación")
    # buy & hold de referencia
    pa = {a: simulate(ts, c, [1.0] * len(c), bars_y, vt) for a, (ts, o, h, l, c) in series.items()}
    d, t = split(portfolio(pa))
    bh = (perf(d, bars_y), perf(t, bars_y))
    print(f"{'comprar y mantener':22s} diseño Sharpe {bh[0]['sharpe']:+.2f} · prueba Sharpe {bh[1]['sharpe']:+.2f} CAGR {bh[1]['cagr']:+.0%} DD {bh[1]['maxdd']:.0%}")
    for name, (fn, params) in SIGNALS.items():
        for mode in (("ls", "lo") if name not in ("dip_buy", "rip_short") else ("x",)):
            best = None
            for p in params:
                pp = p * scale if name in ("tsmom", "ema", "ema_cross", "donchian") else p
                pa = {a: simulate(ts, c, fn(c, h, l, pp, mode), bars_y, vt) for a, (ts, o, h, l, c) in series.items()}
                d, _ = split(portfolio(pa)); pd = perf(d, bars_y)
                if best is None or pd.get("sharpe", -9) > best[1].get("sharpe", -9):
                    best = (pp, pd, pa)
            pp, pd, pa = best
            _, t = split(portfolio(pa)); pt = perf(t, bars_y)
            per = {a: perf(split(rows)[1], bars_y).get("sharpe", 0) for a, rows in pa.items()}
            pos_assets = sum(1 for v in per.values() if v > 0)
            ctl = random_control(series, fn, pp, mode, bars_y, vt, reps=100)
            ok = (pt["sharpe"] >= 0.8 and pt["t"] >= 2 and pt["sharpe"] > ctl["p95"] and pd["sharpe"] > 0 and pos_assets >= 5)
            tag = {"ls": "largo/corto", "lo": "solo largo", "x": ""}[mode]
            print(f"{name:10s} {tag:11s} p={pp:<4} | diseño Sharpe {pd['sharpe']:+.2f} CAGR {pd['cagr']:+.0%} | PRUEBA Sharpe {pt['sharpe']:+.2f} "
                  f"t {pt['t']:+.2f} CAGR {pt['cagr']:+.0%} DD {pt['maxdd']:.0%} expo {pt['expo']:.2f} | azar p50 {ctl['p50']:+.2f} p95 {ctl['p95']:+.2f} "
                  f"| mercados + {pos_assets}/{len(per)} {'✅ PASA' if ok else ''}")
            results.append({"tf": tf, "vt": vt, "strategy": name, "mode": mode, "param": pp, "design": pd, "test": pt, "random": ctl,
                            "per_asset_test_sharpe": per, "pass": ok, "buyhold_test": bh[1]})
    return results


def recent(path, days=4):
    """Qué habría hecho cada estrategia (parámetro elegido en diseño) en los últimos días en SOL y BTC, velas de 1 h."""
    D = json.load(open(path))
    for a in ("SOL", "BTC"):
        rows = D.get(f"{a}USDT_1h") or []
        c = [r[4] for r in rows]; ts = [r[0] for r in rows]
        i0 = next(i for i, t in enumerate(ts) if t >= ts[-1] - days * 86400)
        seg = c[i0:]
        print(f"\n{a} últimos {days} días (1 h): de {seg[0]:.2f} a {seg[-1]:.2f} ({seg[-1]/seg[0]-1:+.1%}); máx {max(seg):.2f}, mín {min(seg):.2f}")
        # cuánto movimiento total hubo (suma de subidas y bajadas de tramos de ≥ 2%)
        pivots = [seg[0]]; d = 0
        for x in seg[1:]:
            if d >= 0 and x > pivots[-1]: pivots[-1] = x if d > 0 else pivots[-1]
            ch = x / pivots[-1] - 1
            if abs(ch) >= 0.02 and (d == 0 or (ch > 0) != (d > 0)):
                pivots.append(x); d = 1 if ch > 0 else -1
            elif d != 0 and ((d > 0 and x > pivots[-1]) or (d < 0 and x < pivots[-1])):
                pivots[-1] = x
        legs = [pivots[i + 1] / pivots[i] - 1 for i in range(len(pivots) - 1)]
        print("  tramos ≥2%:", " ".join(f"{x:+.1%}" for x in legs))


if __name__ == "__main__":
    path = sys.argv[1]
    allr = []
    for tf, vt in (("1d", 0.6), ("1d", None), ("4h", 0.6)):
        allr += run(path, tf, vt)
    recent(path)
    json.dump(allr, open(sys.argv[2] if len(sys.argv) > 2 else "majors_bt_results.json", "w"), indent=1, default=str)
