"""Backtest de perps en Hyperliquid (28/10/2026) con el protocolo del 25/10.

Pregunta: ¿hay alguna señal en perps (largo o corto) que le gane al azar fuera de muestra, después de costos y funding?

- Datos: API pública de Hyperliquid (/info): velas de 1 h y funding horario de 90 días, mercados con volumen diario >= US$5M.
- Entrada a la APERTURA de la vela siguiente a la señal. Stop y toma de ganancia por nivel dentro de la vela, con castigo:
  si una vela toca stop y objetivo, se asume el stop; si abre más allá del stop, se ejecuta en la apertura; el stop paga
  slippage extra. Máximo una posición por mercado y estrategia.
- Costos: comisión taker 0,045% por lado + slippage (0,05% majors, 0,15% memes) + funding real hora por hora.
- Mitad vieja = diseño (se elige la mejor combinación), mitad nueva = prueba. Control: entradas al azar con el mismo
  lado, las mismas salidas y la misma cantidad (20 repeticiones).

Uso: python -m fomo_intel.experiments.perps_bt [pull|analyze|all]   (datos en data/perps/)
"""
from __future__ import annotations

import json
import math
import random
import statistics as stx
import sys
import time
from pathlib import Path

import requests

API = "https://api.hyperliquid.xyz/info"
DATA = Path("data/perps")
DAYS = 90
FEE = 0.00045
MEMES = {"kPEPE", "kBONK", "kSHIB", "kFLOKI", "kNEIRO", "kDOGS", "kLUNC", "DOGE", "WIF", "POPCAT", "FARTCOIN", "PENGU", "TRUMP", "MEW", "BOME",
         "GOAT", "PNUT", "MOODENG", "CHILLGUY", "AI16Z", "SPX", "MOG", "BRETT", "TURBO", "GIGA", "USELESS", "PUMP", "MELANIA", "TST", "VINE",
         "FWOG", "PEOPLE", "MEME", "ANIME", "NEIROETH", "HPOS", "BABY", "ZEREBRO", "GRIFFAIN", "VIRTUAL", "FARTBOY", "BANANA", "ACT", "LAUNCHCOIN"}
MAJORS = {"BTC", "ETH", "SOL"}


def post(body, tries=4):
    for i in range(tries):
        try:
            r = requests.post(API, json=body, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(5 + 5 * i); continue
        except Exception as e:  # noqa: BLE001
            print("  err", body.get("type"), e)
        time.sleep(1 + i)
    return None


# ---------------------------------------------------------------- datos
def pull():
    DATA.mkdir(parents=True, exist_ok=True)
    meta = post({"type": "metaAndAssetCtxs"})
    uni, ctx = meta[0]["universe"], meta[1]
    rows = []
    for u, c in zip(uni, ctx):
        if u.get("isDelisted"):
            continue
        rows.append({"coin": u["name"], "maxLev": u.get("maxLeverage"), "vol": float(c.get("dayNtlVlm") or 0),
                     "oi_usd": float(c.get("openInterest") or 0) * float(c.get("markPx") or 0), "funding": float(c.get("funding") or 0)})
    rows.sort(key=lambda r: -r["vol"])
    keep = [r for r in rows if r["vol"] >= 5e6]
    memes_extra = [r for r in rows if r["coin"] in MEMES and r["vol"] >= 1e6 and r not in keep]
    keep = keep[:70] + memes_extra
    json.dump({"ts": time.time(), "markets": keep, "all": rows}, open(DATA / "universe.json", "w"))
    print(f"mercados: {len(rows)} activos, {len(keep)} con volumen (memes: {sum(1 for r in keep if r['coin'] in MEMES)})")
    end = int(time.time() * 1000); start = end - DAYS * 86400 * 1000
    for k, r in enumerate(keep):
        coin = r["coin"]; fp = DATA / f"{coin}.json"
        if fp.exists() and time.time() - fp.stat().st_mtime < 6 * 3600:
            continue
        cs = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": start, "endTime": end}}) or []
        fund, t = [], start
        while t < end:
            f = post({"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": end}) or []
            if not f:
                break
            fund += f
            nt = max(int(x["time"]) for x in f) + 1
            if nt <= t or len(f) < 400:
                break
            t = nt; time.sleep(0.3)
        json.dump({"coin": coin, "candles": cs, "funding": fund}, open(fp, "w"))
        print(f"  {k + 1}/{len(keep)} {coin}: {len(cs)} velas, {len(fund)} funding")
        time.sleep(0.4)


def load():
    uni = json.load(open(DATA / "universe.json"))
    series = {}
    for r in uni["markets"]:
        fp = DATA / f"{r['coin']}.json"
        if not fp.exists():
            continue
        d = json.load(open(fp))
        cs = sorted(d["candles"], key=lambda c: c["t"])
        if len(cs) < 24 * 30:
            continue
        fmap = {int(x["time"]) // 3600000: float(x["fundingRate"]) for x in d["funding"]}
        t = [int(c["t"]) // 3600000 for c in cs]
        series[r["coin"]] = {"t": t, "o": [float(c["o"]) for c in cs], "h": [float(c["h"]) for c in cs], "l": [float(c["l"]) for c in cs],
                             "c": [float(c["c"]) for c in cs], "v": [float(c["v"]) * float(c["c"]) for c in cs],
                             "f": [fmap.get(x, 0.0) for x in t], "meme": r["coin"] in MEMES, "major": r["coin"] in MAJORS}
    for s in series.values():          # precálculo (solo pasado): volatilidad diaria y mediana de volumen de 48 h
        c, v = s["c"], s["v"]
        lr = [0.0] + [math.log(c[k] / c[k - 1]) if c[k - 1] > 0 else 0.0 for k in range(1, len(c))]
        s["sd"] = [None] * len(c); s["vmed"] = [None] * len(c)
        for i in range(73, len(c)):
            s["sd"][i] = stx.pstdev(lr[i - 71:i + 1]) * math.sqrt(24)
        for i in range(48, len(c)):
            s["vmed"][i] = stx.median(v[i - 48:i]) or 1.0
    return series


# ---------------------------------------------------------------- simulación
def slip(s):
    return 0.0015 if s["meme"] else (0.0005 if s["major"] else 0.001)


def sim_trade(s, i, side, sl, tp, hold):
    """Entra en la apertura de la vela i. sl/tp en fracción de precio (None = sin). Devuelve (retorno neto sobre nocional, salida)."""
    o, h, l, c, f = s["o"], s["h"], s["l"], s["c"], s["f"]
    n = len(c)
    if i >= n:
        return None
    sp = slip(s); entry = o[i] * (1 + side * sp)
    stop = entry * (1 - side * sl) if sl else None
    take = entry * (1 + side * tp) if tp else None
    fund = 0.0; exit_px = None; why = "time"
    last = min(n - 1, i + hold - 1)
    for j in range(i, last + 1):
        fund += -side * f[j]                         # largo paga funding positivo
        if stop is not None:
            hit_stop = (l[j] <= stop) if side > 0 else (h[j] >= stop)
            if hit_stop:
                px = o[j] if ((o[j] <= stop) if side > 0 else (o[j] >= stop)) and j > i else stop
                exit_px = px * (1 - side * sp * 2); why = "stop"; break
        if take is not None:
            hit_tp = (h[j] >= take) if side > 0 else (l[j] <= take)
            if hit_tp:
                exit_px = take * (1 - side * sp); why = "tp"; break
    if exit_px is None:
        exit_px = c[last] * (1 - side * sp)
    ret = side * (exit_px / entry - 1) - 2 * FEE + fund
    return ret, why, j - i + 1


def sigma_d(c, i, w=72):
    """Volatilidad diaria estimada con las últimas w velas de 1 h (solo pasado)."""
    if i < w + 1:
        return None
    r = [math.log(c[k] / c[k - 1]) for k in range(i - w + 1, i + 1) if c[k - 1] > 0]
    return stx.pstdev(r) * math.sqrt(24) if len(r) > 10 else None


def ema(xs, n):
    a = 2 / (n + 1); out = []; e = xs[0]
    for x in xs:
        e = a * x + (1 - a) * e; out.append(e)
    return out


# --- señales: cada función devuelve lista de (i_señal, lado). La entrada es i_señal + 1.
def sig_funding(s, mult):
    f = s["f"]; out = []; base = 0.0000125              # 0,00125%/h ≈ 11% anual (tasa normal de Hyperliquid)
    for i in range(24, len(f)):
        m = sum(f[i - 23:i + 1]) / 24
        if m >= base * mult: out.append((i, -1))         # largos pagan mucho: la multitud está apalancada al alza → short
        elif m <= -base * mult / 2: out.append((i, 1))   # cortos pagan → long
    return out


def sig_cascade(s, k):
    c, v = s["c"], s["v"]; out = []
    for i in range(73, len(c)):
        r = c[i] / c[i - 1] - 1
        sd = s["sd"][i - 1]
        if not sd:
            continue
        s1 = sd / math.sqrt(24)
        med = s["vmed"][i]
        if v[i] >= 3 * med:
            if r <= -k * s1: out.append((i, 1))      # cascada de ventas/liquidaciones → rebote
            elif r >= k * s1: out.append((i, -1))    # squeeze al alza → se desinfla
    return out


def sig_breakout(s, look):
    c, h, l, v = s["c"], s["h"], s["l"], s["v"]; out = []
    for i in range(look + 1, len(c)):
        med = s["vmed"][i] or 1
        if v[i] < 2 * med:
            continue
        if c[i] < min(l[i - look:i]): out.append((i, -1))
        elif c[i] > max(h[i - look:i]): out.append((i, 1))
    return out


def sig_trend(s, fast, slow):
    c = s["c"]; a, b = ema(c, fast), ema(c, slow); out = []
    for i in range(slow, len(c)):
        if a[i - 1] <= b[i - 1] and a[i] > b[i]: out.append((i, 1))
        elif a[i - 1] >= b[i - 1] and a[i] < b[i]: out.append((i, -1))
    return out


SIGNALS = {
    "funding_fade": (sig_funding, [6, 12, 24]),
    "cascade_fade": (sig_cascade, [3, 4]),
    "breakout": (sig_breakout, [48, 72]),
    "trend_ema": (sig_trend, [(24, 96), (12, 48)]),
}
EXITS = [(sl, tp, hold) for hold in (12, 24, 48) for sl in (1.0, 2.0) for tp in (1.0, 2.0, None)]   # sl/tp en sigmas diarios


def run_events(series, name, param, ex, lo, hi, side_filter=None, rnd=None, counts=None):
    """Simula una estrategia en la ventana de horas [lo, hi). rnd: Random para el control (mismas salidas, entradas al azar)."""
    fn, _ = SIGNALS[name]
    sl_k, tp_k, hold = ex
    res = []
    for coin, s in series.items():
        t = s["t"]
        if rnd is None:
            sigs = fn(s, *param) if isinstance(param, tuple) else fn(s, param)
        else:
            k = counts.get(coin, 0)
            idx = [i for i in range(80, len(t) - 1) if lo <= t[i] < hi]
            sigs = [(rnd.choice(idx), side) for side in counts.get(coin + ":sides", [])][:k] if idx else []
            sigs.sort()
        busy = -1
        for i, side in sigs:
            if not (lo <= t[i] < hi) or i + 1 >= len(t) or i + 1 <= busy:
                continue
            if side_filter and side != side_filter:
                continue
            sd = s["sd"][i]
            if not sd:
                continue
            r = sim_trade(s, i + 1, side, sl_k * sd, tp_k * sd if tp_k else None, hold)
            if r is None:
                continue
            busy = i + r[2]
            res.append({"coin": coin, "side": side, "ret": r[0], "why": r[1], "i": i, "meme": s["meme"]})
    return res


def stats(res):
    if not res:
        return {"n": 0}
    rs = [r["ret"] for r in res]
    return {"n": len(rs), "win": round(sum(1 for x in rs if x > 0) / len(rs), 3), "mean": round(stx.mean(rs) * 100, 3),
            "median": round(stx.median(rs) * 100, 3), "sum": round(sum(rs) * 100, 1),
            "long_n": sum(1 for r in res if r["side"] > 0), "short_n": sum(1 for r in res if r["side"] < 0),
            "worst": round(min(rs) * 100, 1),
            "t": round(stx.mean(rs) / (stx.pstdev(rs) / math.sqrt(len(rs))), 2) if len(rs) > 2 and stx.pstdev(rs) > 0 else 0}


def control(series, name, param, ex, lo, hi, real, reps=20):
    counts = {}
    for r in real:
        counts[r["coin"]] = counts.get(r["coin"], 0) + 1
        counts.setdefault(r["coin"] + ":sides", []).append(r["side"])
    out = []
    for k in range(reps):
        out += run_events(series, name, param, ex, lo, hi, rnd=random.Random(1000 + k), counts=counts)
    return stats(out)


def xs_momentum(series, lo, hi, look_d, hold_d, reverse, rnd=None, k=2):
    """Pares largo/corto entre memes: cada día a las 00 UTC, largo en los k mejores de los últimos look_d días y corto en los k peores
    (reverse=True al revés). Casi neutral al mercado. Retorno por día = (largos − cortos)/2 neto de costos y funding."""
    memes = {c: s for c, s in series.items() if s["meme"]}
    if len(memes) < 2 * k + 2:
        return []
    idx = {c: {h: i for i, h in enumerate(s["t"])} for c, s in memes.items()}
    out = []
    first = max(lo, min(s["t"][0] for s in memes.values()) + look_d * 24)
    h0 = (first // 24 + 1) * 24
    for h in range(h0, hi - hold_d * 24, hold_d * 24):
        sc = []
        for c, s in memes.items():
            i, j = idx[c].get(h), idx[c].get(h - look_d * 24)
            if i is None or j is None or i + hold_d * 24 >= len(s["t"]):
                continue
            sc.append((s["c"][i - 1] / s["c"][j] - 1, c, i))
        if len(sc) < 2 * k + 2:
            continue
        sc.sort()
        if rnd:
            rnd.shuffle(sc)
        longs, shorts = (sc[-k:], sc[:k]) if not reverse else (sc[:k], sc[-k:])
        day = 0.0
        for grp, side in ((longs, 1), (shorts, -1)):
            for _, c, i in grp:
                s = memes[c]; e = i + hold_d * 24 - 1
                r = side * (s["c"][e] / s["o"][i] - 1) - 2 * (FEE + slip(s)) - side * sum(s["f"][i:e + 1])
                day += r / (2 * k)
        out.append({"coin": "pair", "side": 0, "ret": day, "i": h})
    return out


def analyze():
    series = load()
    if not series:
        print("sin datos"); return
    allh = sorted({h for s in series.values() for h in s["t"]})
    lo, hi = allh[0], allh[-1] + 1
    mid = lo + (hi - lo) // 2
    print(f"mercados {len(series)} (memes {sum(s['meme'] for s in series.values())}), {len(allh)} horas, "
          f"diseño {time.strftime('%d/%m', time.gmtime(lo * 3600))}–{time.strftime('%d/%m', time.gmtime(mid * 3600))}, "
          f"prueba hasta {time.strftime('%d/%m', time.gmtime(hi * 3600))}")
    # contexto: comprar y mantener en la prueba
    bh = []
    for s in series.values():
        i0 = next((i for i, h in enumerate(s["t"]) if h >= mid), None)
        if i0 is not None:
            bh.append(s["c"][-1] / s["o"][i0] - 1)
    print(f"comprar y mantener en la prueba: mediana {stx.median(bh) * 100:+.1f}%, media {stx.mean(bh) * 100:+.1f}%")
    summary = []
    groups = [("todos", lambda s: True), ("memes", lambda s: s["meme"]), ("no memes", lambda s: not s["meme"])]
    for gname, gf in groups:
        sub = {c: s for c, s in series.items() if gf(s)}
        if len(sub) < 3:
            continue
        print(f"\n######## universo: {gname} ({len(sub)} mercados)")
        for name, (fn, params) in SIGNALS.items():
            best = None; grid = []
            for p in params:
                for ex in EXITS:
                    d = stats(run_events(sub, name, p, ex, lo, mid))
                    if d["n"] >= 30:
                        grid.append((p, ex, d))
                        if best is None or d["mean"] > best[2]["mean"]:
                            best = (p, ex, d)
            if not best:
                print(f"{name}: muestra chica"); continue
            p, ex = best[0], best[1]
            test = run_events(sub, name, p, ex, mid, hi)
            t = stats(test); ctl = control(sub, name, p, ex, mid, hi, test)
            pos_test = sum(1 for g in grid if stats(run_events(sub, name, g[0], g[1], mid, hi)).get("mean", -1) > 0)
            print(f"{name:13s} mejor {p} sl{ex[0]}σ tp{ex[1]}σ {ex[2]}h | diseño n{best[2]['n']} {best[2]['win']:.0%} {best[2]['mean']:+.2f}%/op "
                  f"| PRUEBA n{t.get('n')} {t.get('win', 0):.0%} {t.get('mean', 0):+.2f}%/op t={t.get('t', 0)} med {t.get('median', 0):+.2f} peor {t.get('worst', 0)} "
                  f"L{t.get('long_n')}/S{t.get('short_n')} | azar {ctl.get('win', 0):.0%} {ctl.get('mean', 0):+.2f}%/op | combos+ en prueba {pos_test}/{len(grid)}")
            summary.append({"universe": gname, "strategy": name, "param": p, "exit": ex, "design": best[2], "test": t, "random": ctl,
                            "grid_positive_test": pos_test, "grid": len(grid)})
    print("\n######## pares largo/corto entre memes (neutral al mercado)")
    for reverse in (False, True):
        for look in (3, 7):
            for hold in (1, 3):
                d = stats(xs_momentum(series, lo, mid, look, hold, reverse))
                t = stats(xs_momentum(series, mid, hi, look, hold, reverse))
                rr = []
                for k in range(20):
                    rr += xs_momentum(series, mid, hi, look, hold, reverse, rnd=random.Random(k))
                c = stats(rr)
                lab = ("reversión" if reverse else "momentum") + f" {look}d→{hold}d"
                print(f"{lab:20s} | diseño n{d.get('n')} {d.get('win', 0):.0%} {d.get('mean', 0):+.2f}%/período | PRUEBA n{t.get('n')} {t.get('win', 0):.0%} "
                      f"{t.get('mean', 0):+.2f}% t={t.get('t', 0)} suma {t.get('sum', 0):+.1f}% | azar {c.get('mean', 0):+.2f}%")
                summary.append({"universe": "memes", "strategy": "pairs_" + ("rev" if reverse else "mom"), "param": [look, hold], "design": d, "test": t, "random": c})
    json.dump({"ts": time.time(), "results": summary}, open(DATA / "results.json", "w"), indent=1)
    print("\nCriterio para pasar a paper: PRUEBA con n >= 30, media > 0, t >= 2,5 (no es ruido, con ~20 pruebas), media > azar + 0,3%/op y diseño también positivo.")
    ok = [r for r in summary if r["test"].get("n", 0) >= 30 and r["test"].get("mean", -9) > 0 and r["test"].get("t", 0) >= 2.5
          and r["test"]["mean"] > r["random"].get("mean", 0) + 0.3 and r["design"].get("mean", -9) > 0 and r["design"].get("t", 0) >= 1]
    print("PASAN:", [(r["universe"], r["strategy"], r["param"], r["test"]["mean"]) for r in ok] or "ninguna")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("pull", "all"):
        pull()
    if cmd in ("analyze", "all"):
        analyze()
