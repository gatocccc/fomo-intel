"""Mercados cruzados → cripto en ventanas de horas (30/10/2026, pedido de Gastón: "el mercado de stocks influye sobre cripto,
el oro y la plata influyen sobre cripto; nos falta tradear en time frames cortos").

Hipótesis que se prueba: la información arranca en otro mercado (Nasdaq, oro, plata, dólar) y cripto tarda horas en digerirla.
Si es así, hay una ventaja de corto plazo que NO depende de velocidad sino de leer el mercado que se movió primero.
Todo lo anterior (perps_bt, majors_bt) miraba el precio de cripto solo; esto mira el de afuera.

Datos (los baja este mismo script, corre en el servidor): Yahoo 1 h, 730 días (NQ=F Nasdaq, ES=F S&P, GC=F oro, SI=F plata,
DX-Y.NYB dólar) + Binance 1 h (BTC, ETH, SOL). Alineados por hora UTC.
Protocolo: mitad de diseño (primer año) / mitad de prueba (segundo año); control al azar ×300; costos perps 0,12% ida y vuelta.

Preguntas:
 A) lead-lag: ¿el retorno de 1 h de X predice la hora siguiente de Y? (correlaciones con retraso 0, +1, +2, +3 y al revés)
 B) shock horario: |X_t| ≥ 2σ → Y en las 1, 3, 6 h siguientes (continuación o nada), vs. azar
 C) premarket: X entre 08:00 y 13:00 UTC ≥ ±1% → Y entre 13:00–17:00 y 13:00–21:00 UTC
 D) días de shock: X diario (21:00 UTC) ≤ −2% / ≥ +2% → Y en las 24 h y 48 h siguientes, separado por si cripto ya cayó ese día
 E) regla operable: tras shock bajista de X (≤ −2σ), corto en Y por k horas, con costos; diseño/prueba; vs. azar

Uso: python -m fomo_intel.experiments.cross_bt [salida.json]
"""
from __future__ import annotations

import json
import math
import random
import statistics as stx
import sys
import time

import requests

EXT = {"NQ": "NQ=F", "ES": "ES=F", "GOLD": "GC=F", "SILVER": "SI=F", "DXY": "DX-Y.NYB"}
CRYPTO = ["BTC", "ETH", "SOL"]
COST_RT = 0.0012  # perps ida y vuelta (comisión + slippage)
UA = {"User-Agent": "Mozilla/5.0"}


def get(u, **kw):
    for i in range(4):
        try:
            r = requests.get(u, timeout=30, **kw)
            if r.status_code == 200:
                return r
            print("http", r.status_code, u[:70], file=sys.stderr)
        except Exception as e:
            print("err", u[:70], e, file=sys.stderr)
        time.sleep(2 + 2 * i)
    return None


def yahoo_1h(tk):
    r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}", params={"range": "730d", "interval": "1h"}, headers=UA)
    if not r:
        r = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{tk}", params={"range": "730d", "interval": "1h"}, headers=UA)
    if not r:
        return {}
    try:
        j = r.json()["chart"]["result"][0]
        q = j["indicators"]["quote"][0]
        out = {}
        for t, c in zip(j["timestamp"], q["close"]):
            if c:
                out[(int(t) // 3600) * 3600] = float(c)
        return out
    except Exception as e:
        print("yahoo parse", tk, e, file=sys.stderr)
        return {}


def binance_1h(sym, start_ms):
    out = {}
    for host in ("https://data-api.binance.vision", "https://api.binance.com"):
        t = start_ms
        out = {}
        while True:
            r = get(f"{host}/api/v3/klines", params={"symbol": sym, "interval": "1h", "startTime": t, "limit": 1000})
            if not r:
                break
            k = r.json()
            if not k:
                break
            for x in k:
                out[int(x[0] // 1000)] = float(x[4])
            if len(k) < 1000:
                break
            t = k[-1][0] + 1
        if out:
            break
    return out


# ------------------------------------------------------------------ utilidades
def hourly_returns(px):
    """dict hora→cierre  →  dict hora→retorno de la vela que cierra en esa hora (respecto del cierre anterior disponible,
    solo si el anterior es la hora inmediata previa; así no se mezclan gaps de fin de semana con horas normales)."""
    ks = sorted(px)
    r = {}
    for a, b in zip(ks, ks[1:]):
        if b - a == 3600 and px[a] > 0:
            r[b] = px[b] / px[a] - 1
    return r


def fwd(px, t, h):
    """retorno de Y desde el cierre en t hasta el cierre en t+h (cripto es 24/7: casi siempre existe)."""
    a, b = px.get(t), px.get(t + h * 3600)
    return (b / a - 1) if (a and b) else None


def rolling_sd(vals, w=500):
    """desvío de las w observaciones previas (sin incluir la actual), O(n)."""
    out = [None] * len(vals); s1 = s2 = 0.0
    for i, v in enumerate(vals):
        if i >= w:
            m = s1 / w; var = max(s2 / w - m * m, 0.0); out[i] = math.sqrt(var)
            old = vals[i - w]; s1 -= old; s2 -= old * old
        s1 += v; s2 += v * v
    return out


def tstat(xs):
    n = len(xs)
    if n < 3:
        return 0.0
    sd = stx.pstdev(xs)
    return (stx.mean(xs) / (sd / math.sqrt(n))) if sd > 0 else 0.0


def corr(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx, my = stx.mean(xs), stx.mean(ys)
    sx, sy = stx.pstdev(xs), stx.pstdev(ys)
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)


def summarize(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean_pct": round(100 * stx.mean(xs), 3), "hit": round(sum(1 for x in xs if x > 0) / len(xs), 3),
            "t": round(tstat(xs), 2), "median_pct": round(100 * stx.median(xs), 3)}


def random_control(pool, n, reps=300):
    """media de n retornos tomados al azar del universo, p5/p95 (para saber si lo condicional es distinto del azar)."""
    if n < 3 or len(pool) < n:
        return None
    ms = sorted(stx.mean(random.sample(pool, n)) for _ in range(reps))
    return {"p5_pct": round(100 * ms[int(0.05 * reps)], 3), "p95_pct": round(100 * ms[int(0.95 * reps)], 3),
            "mean_pct": round(100 * stx.mean(ms), 3)}


# ------------------------------------------------------------------ análisis
def lead_lag(rx, ry):
    """correlaciones X_t vs Y_{t+k}, k=0..3, y al revés Y_t vs X_{t+k}."""
    out = {}
    for k in range(0, 4):
        xs, ys = [], []
        for t, x in rx.items():
            y = ry.get(t + k * 3600)
            if y is not None:
                xs.append(x); ys.append(y)
        c = corr(xs, ys)
        out[f"X_t->Y_t+{k}"] = {"corr": None if c is None else round(c, 3), "n": len(xs)}
    for k in range(1, 3):
        xs, ys = [], []
        for t, y in ry.items():
            x = rx.get(t + k * 3600)
            if x is not None:
                xs.append(y); ys.append(x)
        c = corr(xs, ys)
        out[f"Y_t->X_t+{k}"] = {"corr": None if c is None else round(c, 3), "n": len(xs)}
    return out


def hourly_shocks(rx, py, ry, split, sigma_mult=2.0):
    """|X_t| ≥ k·σ_X (σ sobre las 500 horas previas, sin mirar el futuro) → Y en 1,3,6 h. Separado por signo y por mitad."""
    ks = sorted(rx)
    vals = [rx[k] for k in ks]
    res = {}
    pool = {h: [v for v in (fwd(py, t, h) for t in ry) if v is not None] for h in (1, 3, 6)}
    for sign, name in ((-1, "down"), (1, "up")):
        for half in ("design", "test"):
            for h in (1, 3, 6):
                res[f"{name}_{half}_{h}h"] = []
    sds = rolling_sd(vals)
    for i in range(500, len(ks)):
        sd = sds[i]
        if not sd:
            continue
        x = vals[i]
        if abs(x) < sigma_mult * sd:
            continue
        t = ks[i]
        half = "design" if t < split else "test"
        name = "down" if x < 0 else "up"
        for h in (1, 3, 6):
            v = fwd(py, t, h)
            if v is not None:
                res[f"{name}_{half}_{h}h"].append(v)
    out = {}
    for k, xs in res.items():
        s = summarize(xs)
        h = int(k.split("_")[-1][:-1])
        s["random"] = random_control(pool[h], len(xs))
        out[k] = s
    return out


def premarket(px_x, py, split):
    """X 08:00→13:00 UTC ≥ ±1% → Y 13:00→17:00 y 13:00→21:00 UTC (días hábiles)."""
    out = {}
    buckets = {}
    pool4, pool8 = [], []
    for t in sorted(px_x):
        if (t % 86400) // 3600 != 13:
            continue
        a = px_x.get(t - 5 * 3600)
        if not a:
            continue
        gx = px_x[t] / a - 1
        y4, y8 = fwd(py, t, 4), fwd(py, t, 8)
        if y4 is None or y8 is None:
            continue
        pool4.append(y4); pool8.append(y8)
        half = "design" if t < split else "test"
        if gx <= -0.01:
            key = f"pre_down_{half}"
        elif gx >= 0.01:
            key = f"pre_up_{half}"
        else:
            continue
        buckets.setdefault(key, {"4h": [], "8h": [], "x": []})
        buckets[key]["4h"].append(y4); buckets[key]["8h"].append(y8); buckets[key]["x"].append(gx)
    for k, b in buckets.items():
        out[k] = {"x_mean_pct": round(100 * stx.mean(b["x"]), 2), "y_4h": summarize(b["4h"]), "y_8h": summarize(b["8h"]),
                  "random_4h": random_control(pool4, len(b["4h"])), "random_8h": random_control(pool8, len(b["8h"]))}
    return out


def daily_shocks(px_x, py, split, thr=0.02):
    """X cierre 21:00 UTC vs 21:00 UTC anterior ≤ −thr o ≥ +thr → Y 24 h y 48 h siguientes.
    Además separa por lo que hizo Y ese mismo día (¿ya lo descontó?)."""
    out = {}
    days = sorted(t for t in px_x if (t % 86400) // 3600 == 21)
    pool24 = [v for v in (fwd(py, t, 24) for t in days) if v is not None]
    pool48 = [v for v in (fwd(py, t, 48) for t in days) if v is not None]
    b = {}
    for a, t in zip(days, days[1:]):
        if t - a > 86400 * 4:
            continue
        gx = px_x[t] / px_x[a] - 1
        if abs(gx) < thr:
            continue
        y24, y48 = fwd(py, t, 24), fwd(py, t, 48)
        ysame = (py[t] / py[a] - 1) if (py.get(t) and py.get(a)) else None
        if y24 is None or y48 is None or ysame is None:
            continue
        half = "design" if t < split else "test"
        name = "down" if gx < 0 else "up"
        key = f"day_{name}_{half}"
        b.setdefault(key, {"24h": [], "48h": [], "x": [], "ysame": [], "y24_if_y_already_moved": [], "y24_if_y_flat": []})
        b[key]["24h"].append(y24); b[key]["48h"].append(y48); b[key]["x"].append(gx); b[key]["ysame"].append(ysame)
        # ¿cripto ya acompañó? (mismo signo y ≥ 1,5%)
        if (gx < 0 and ysame <= -0.015) or (gx > 0 and ysame >= 0.015):
            b[key]["y24_if_y_already_moved"].append(y24)
        else:
            b[key]["y24_if_y_flat"].append(y24)
    for k, v in b.items():
        out[k] = {"x_mean_pct": round(100 * stx.mean(v["x"]), 2), "y_same_day_mean_pct": round(100 * stx.mean(v["ysame"]), 2),
                  "y_24h": summarize(v["24h"]), "y_48h": summarize(v["48h"]),
                  "y_24h_if_y_already_moved": summarize(v["y24_if_y_already_moved"]),
                  "y_24h_if_y_flat": summarize(v["y24_if_y_flat"]),
                  "random_24h": random_control(pool24, len(v["24h"])), "random_48h": random_control(pool48, len(v["48h"]))}
    return out


def rule_short_after_shock(rx, py, split, sigma_mult=2.0, hold_h=(3, 6, 12), cooldown_h=12):
    """Regla operable: X cae ≥ 2σ en una hora → corto en Y al cierre de esa hora, cerrar a las k horas. Costos incluidos.
    Sin solapamiento (cooldown). Reporta diseño/prueba y control al azar con el mismo n."""
    ks = sorted(rx); vals = [rx[k] for k in ks]
    out = {}
    for hold in hold_h:
        trades = {"design": [], "test": []}
        pool = [(-v - COST_RT) for v in (fwd(py, t, hold) for t in sorted(py)) if v is not None]
        last = -10 ** 12
        sds = rolling_sd(vals)
        for i in range(500, len(ks)):
            sd = sds[i]
            if not sd or vals[i] > -sigma_mult * sd:
                continue
            t = ks[i]
            if t - last < cooldown_h * 3600:
                continue
            v = fwd(py, t, hold)
            if v is None:
                continue
            last = t
            trades["design" if t < split else "test"].append(-v - COST_RT)
        out[f"short_{hold}h"] = {h: summarize(tr) for h, tr in trades.items()}
        out[f"short_{hold}h"]["random_test"] = random_control(pool, len(trades["test"]))
        out[f"short_{hold}h"]["sum_test_pct"] = round(100 * sum(trades["test"]), 2)
    return out


def main():
    outpath = sys.argv[1] if len(sys.argv) > 1 else "state/research/cross_asset.json"
    random.seed(7)
    t0 = time.time()
    px = {}
    for name, tk in EXT.items():
        px[name] = yahoo_1h(tk)
        print("yahoo", name, len(px[name]), file=sys.stderr)
    start_ms = int((time.time() - 735 * 86400) * 1000)
    for c in CRYPTO:
        px[c] = binance_1h(c + "USDT", start_ms)
        print("binance", c, len(px[c]), file=sys.stderr)
    rets = {k: hourly_returns(v) for k, v in px.items()}
    all_ts = sorted(set().union(*[set(v) for v in px.values() if v]))
    if not all_ts:
        print("sin datos"); return
    split = all_ts[0] + (all_ts[-1] - all_ts[0]) // 2
    res = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "split_utc": time.strftime("%Y-%m-%d", time.gmtime(split)),
           "range": [time.strftime("%Y-%m-%d", time.gmtime(all_ts[0])), time.strftime("%Y-%m-%d", time.gmtime(all_ts[-1]))],
           "bars": {k: len(v) for k, v in px.items()}, "cost_rt": COST_RT, "pairs": {}}
    for x in EXT:
        if len(px[x]) < 1000:
            continue
        for y in CRYPTO:
            if len(px[y]) < 1000:
                continue
            res["pairs"][f"{x}->{y}"] = {
                "lead_lag": lead_lag(rets[x], rets[y]),
                "hourly_shocks_2sigma": hourly_shocks(rets[x], px[y], rets[y], split),
                "premarket": premarket(px[x], px[y], split),
                "daily_shocks_2pct": daily_shocks(px[x], px[y], split),
                "rule_short_after_shock": rule_short_after_shock(rets[x], px[y], split),
            }
            print("ok", x, y, round(time.time() - t0), "s", file=sys.stderr)
    # también cripto → Nasdaq (¿quién va primero?)
    if len(px.get("NQ", {})) > 1000 and len(px.get("BTC", {})) > 1000:
        res["pairs"]["BTC->NQ"] = {"lead_lag": lead_lag(rets["BTC"], rets["NQ"]), "hourly_shocks_2sigma": hourly_shocks(rets["BTC"], px["NQ"], rets["NQ"], split)}
    import os
    os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)
    json.dump(res, open(outpath, "w"), indent=1)
    # resumen legible
    print(f"\n== cross_bt {res['generated']}  rango {res['range']}  split {res['split_utc']}  barras {res['bars']}")
    for pair, d in res["pairs"].items():
        ll = d["lead_lag"]
        print(f"\n[{pair}] corr lag0 {ll['X_t->Y_t+0']['corr']}  +1h {ll['X_t->Y_t+1']['corr']}  +2h {ll['X_t->Y_t+2']['corr']}  "
              f"| al revés +1h {ll['Y_t->X_t+1']['corr']}")
        hs = d.get("hourly_shocks_2sigma", {})
        for k in ("down_test_1h", "down_test_3h", "down_test_6h", "up_test_1h", "up_test_3h", "up_test_6h"):
            s = hs.get(k, {})
            if s.get("n"):
                r = s.get("random") or {}
                print(f"  shock {k}: n={s['n']} media {s['mean_pct']}% hit {s['hit']} t={s['t']}  azar p5/p95 {r.get('p5_pct')}/{r.get('p95_pct')}")
        for k, s in d.get("premarket", {}).items():
            if k.endswith("test"):
                print(f"  {k}: n={s['y_4h']['n']} X {s['x_mean_pct']}%  Y4h {s['y_4h']['mean_pct']}% (t {s['y_4h']['t']})  Y8h {s['y_8h']['mean_pct']}% (t {s['y_8h']['t']})  azar4h {s['random_4h']}")
        for k, s in d.get("daily_shocks_2pct", {}).items():
            print(f"  {k}: n={s['y_24h']['n']} X {s['x_mean_pct']}% Y mismo día {s['y_same_day_mean_pct']}%  Y24h {s['y_24h']['mean_pct']}% (hit {s['y_24h']['hit']}, t {s['y_24h']['t']})  "
                  f"Y48h {s['y_48h']['mean_pct']}%  | si Y ya cayó: {s['y_24h_if_y_already_moved'].get('mean_pct')}% n={s['y_24h_if_y_already_moved']['n']}  si Y plano: {s['y_24h_if_y_flat'].get('mean_pct')}% n={s['y_24h_if_y_flat']['n']}  azar24h {s['random_24h']}")
        for k, s in d.get("rule_short_after_shock", {}).items():
            print(f"  regla {k}: diseño {s['design']}  prueba {s['test']}  suma prueba {s['sum_test_pct']}%  azar {s['random_test']}")
    print(f"\nlisto en {round(time.time() - t0)} s → {outpath}")


if __name__ == "__main__":
    main()
