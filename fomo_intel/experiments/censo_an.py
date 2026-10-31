"""Análisis del censo de memecoins (ver censo.py). Corre local o en el servidor sobre state/research/censo/*.json.gz.

1. vida: supervivencia por minuto, % que alcanza cada valuación, tiempo al pico, caída desde el pico.
2. escalones: dada una moneda que toca X por primera vez, P(tocar k·X antes de caer a X/2), por edad.
3. canastas: entrar en N monedas con una regla, salida "recuperar lo invertido a k-x + resto libre",
   costos por tamaño de ticket, mitad diseño / mitad prueba, Monte Carlo de canastas.

Uso: python3 -m fomo_intel.experiments.censo_an [dir] > informe.txt
"""
from __future__ import annotations

import gzip
import json
import math
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

LEVELS = [10_000, 20_000, 30_000, 50_000, 75_000, 100_000, 200_000, 300_000, 500_000, 1_000_000, 3_000_000, 10_000_000]


SOL_USD = 95.0
SOL_RESCALE = False   # 31/10: el reescalado inventaba bombas (tokens muertos de verdad a US$10-70). Por defecto, crudo = conservador.
DROPPED = defaultdict(int)


def units(r, k):
    """Solana Tracker devuelve algunos minutos cotizados en SOL aunque diga USD. En la curva de pump.fun la valuación
    no puede bajar de ~US$2.500 (piso inicial), así que un cierre < 1.500 es un minuto en SOL: se reescala ese minuto.
    Si después de eso queda un salto > 30x entre minutos operados consecutivos, la serie se descarta."""
    if not SOL_RESCALE:
        return True
    g = r[k]; n = len(g["c"]); fixed = 0
    for j in range(n):
        if 0 < g["c"][j] < 1500:
            for key in ("h", "l", "c"):
                g[key][j] = int(g[key][j] * SOL_USD)
            fixed += 1
        elif g["c"][j] >= 1500:
            if 0 < g["l"][j] < 1500: g["l"][j] = int(g["l"][j] * SOL_USD) if g["l"][j] * SOL_USD < g["c"][j] * 1.5 else g["c"][j]
    if fixed:
        r["_sol_quoted"] = True
    return True


def fake(r):
    """Precio fabricado (USDF, AODF, UDTF...: 'valen' US$150M con US$9K de volumen). Un pico real de valuación
    exige volumen: se descarta si el pico supera 20x el volumen acumulado hasta ese minuto (con pico > 100K)."""
    g = r["g1"]; C = g["c"]
    if not C:
        return False
    pk = max(range(len(C)), key=lambda j: C[j])
    if C[pk] < 100_000:
        return False
    cum = sum(g["v"][: pk + 1])
    if C[pk] > 20 * max(cum, 1):
        DROPPED["fabricado_" + r["s"]] += 1
        return True
    return False


def clean(g):
    """Las mechas de 1 minuto son engañosas (una compra gigante en el bloque de creación da máximos de 90x sobre el cierre).
    Máximo y mínimo efectivos acotados a 1,5x del rango de cierres vecinos: lo que un bot podría haber ejecutado."""
    C = g["c"]; H, L = [], []
    for j in range(len(C)):
        a = max(C[j], C[j - 1] if j else C[j]); b = min(C[j], C[j - 1] if j else C[j])
        H.append(min(g["h"][j], int(a * 1.5))); L.append(max(g["l"][j], int(b / 1.5)))
    g["h"], g["l"] = H, L
    return g


def load(d):
    d = Path(d)
    rows = {s: json.load(gzip.open(d / f"{s}.json.gz", "rt")) for s in "ABC" if (d / f"{s}.json.gz").exists()}
    for s_, rs in list(rows.items()):
        keep = []
        for r in rs:
            ok = all(units(r, k) for k in ("g1", "g5") if k in r) and not fake(r)
            if not ok:
                DROPPED[s_] += 1; continue
            for k in ("g1", "g5"):
                if k in r:
                    clean(r[k])
            keep.append(r)
        rows[s_] = keep
    print("descartadas por unidades inconsistentes:", dict(DROPPED), "· cotizadas en SOL reescaladas:",
          {s_: sum(1 for r in rs if r.get("_sol_quoted")) for s_, rs in rows.items()})
    tot = json.load(open(d / "totals.json")) if (d / "totals.json").exists() else []
    return rows, tot


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "  n/a"


def fmt(x):
    return f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}K"


# ---------------------------------------------------------------- 1. vida
def life(rows, name, g="g1", step_min=1):
    n = len(rows)
    print(f"\n=== VIDA · estrato {name} · n={n} (velas {g}) ===")
    last = [r[g]["last"] for r in rows]
    nb = len(rows[0][g]["c"]) if rows else 0
    marks = [m for m in (1, 3, 5, 10, 15, 30, 60, 120, 240, 359, 575) if m < nb]
    print("sigue operándose (hubo un trade en o después del minuto):")
    print("  " + "  ".join(f"{m*step_min:>4}m:{pct(sum(l >= m for l in last), n)}" for m in marks))
    peaks = [max(r[g]["h"]) if r[g]["h"] else 0 for r in rows]
    print("llega a una valuación (máximo dentro de la ventana):")
    print("  " + "  ".join(f"{fmt(L)}:{pct(sum(p >= L for p in peaks), n)}" for L in LEVELS))
    tpk = [r[g]["h"].index(max(r[g]["h"])) * step_min for r, p in zip(rows, peaks) if p >= 30_000]
    if tpk:
        tpk.sort(); print(f"minuto del pico (las que pasaron 30K, n={len(tpk)}): p25 {tpk[len(tpk)//4]} · mediana {tpk[len(tpk)//2]} · p75 {tpk[3*len(tpk)//4]}")
    fin = [r[g]["c"][-1] / p for r, p in zip(rows, peaks) if p >= 30_000 and p > 0]
    if fin:
        fin.sort(); print(f"valor al final de la ventana / pico (las que pasaron 30K): mediana {fin[len(fin)//2]:.2f} · p75 {fin[3*len(fin)//4]:.2f} · p90 {fin[int(.9*len(fin))]:.2f}")
    return peaks


# ---------------------------------------------------------------- 2. escalones
def ladder(rows, name, g="g1", step_min=1, ups=(1.5, 2, 3, 5), down=0.5):
    print(f"\n=== ESCALONES · {name} · P(tocar k·X antes de caer a {down}·X), desde el primer toque de X ===")
    print("   X       n    edad med  " + "  ".join(f"{k}x" for k in ups) + "   | ninguna (muere o queda en rango)")
    out = {}
    for X in LEVELS[1:10]:
        hits = defaultdict(int); n = 0; ages = []
        for r in rows:
            H, L = r[g]["h"], r[g]["l"]
            t = next((i for i, h in enumerate(H) if h >= X), None)
            if t is None:
                continue
            n += 1; ages.append(t * step_min)
            for k in ups:
                for j in range(t + 1, len(H)):
                    if L[j] <= down * X:
                        break
                    if H[j] >= k * X:
                        hits[k] += 1; break
        if n >= 15:
            ages.sort()
            out[X] = {k: hits[k] / n for k in ups} | {"n": n}
            print(f"  {fmt(X):>6} {n:6d}   {ages[n//2]:6d}m   " + "  ".join(f"{100*hits[k]/n:3.0f}%" for k in ups))
    return out


# ---------------------------------------------------------------- 3. canastas
def cost_side(ticket):
    """Costo por lado: 1,25% comisiones (pump.fun/plataforma) + slippage ~1% + fijo US$0,04 (prioridad+gas).
    Ruta directa a la curva (sin la plataforma): ~1,25% + US$0,02 -> usar cost_side = lambda tk: 0.0125 + 0.02/tk."""
    return 0.0225 + 0.04 / max(ticket, 0.01)


def trade(r, entry_bin, ticket, rec_k, rec_frac, stop, trail, g="g1"):
    """Retorno neto en US$ de un ticket. Entrada al cierre del bin +3% de precio corrido.
    rec_k: al tocar rec_k·entrada se vende rec_frac (recuperar). Resto: trailing desde el pico (trail) o fin de ventana.
    stop: si cae a (1-stop)·entrada antes de recuperar, se vende todo. Velas sin trades = no se puede vender ese minuto."""
    H, L, C, V = r[g]["h"], r[g]["l"], r[g]["c"], r[g]["v"]
    e = C[entry_bin] * 1.03
    if e <= 0:
        return None
    cs = cost_side(ticket)
    qty = 1.0; cash = -ticket * (1 + cs); got = False; peak = e
    for j in range(entry_bin + 1, len(H)):
        traded = V[j] > 0
        if not traded:
            continue
        peak = max(peak, H[j])
        if not got and stop and L[j] <= (1 - stop) * e:
            px = min(C[j], (1 - stop) * e)
            cash += qty * ticket * px / e * (1 - cs); return cash
        if not got and H[j] >= rec_k * e:
            cash += rec_frac * ticket * rec_k * (1 - cs); qty -= rec_frac; got = True
        if got and trail and L[j] <= (1 - trail) * peak and peak >= rec_k * e:
            px = min(C[j], (1 - trail) * peak)
            cash += qty * ticket * px / e * (1 - cs); return cash
    last = C[-1]
    alive = r[g]["last"] >= len(H) - 30
    px = last   # la curva de pump.fun y los pools de PumpSwap (LP quemada) siempre tienen liquidez: se vende al último precio
    cash += qty * ticket * px / e * (1 - cs)
    return cash


def entries(rows, rule, g="g1"):
    """rule: ('min', m) entra al minuto m si sigue viva; ('lvl', X, maxage) entra al primer toque de X antes de maxage min."""
    out = []
    for r in rows:
        H, C, V = r[g]["h"], r[g]["c"], r[g]["v"]
        if rule[0] == "min":
            m = rule[1]
            if r[g]["last"] >= m and C[m] >= 2000:
                out.append((r, m))
        else:
            X, maxage = rule[1], rule[2]
            t = next((i for i, h in enumerate(H) if h >= X), None)
            if t is not None and t <= maxage and C[t] >= 2000:
                out.append((r, t))
    return out


def baskets(rows, name, g="g1"):
    print(f"\n=== CANASTAS · {name} ===")
    rows = sorted(rows, key=lambda r: r["created"])
    half = len(rows) // 2
    rules = [("min", 1), ("min", 3), ("min", 10), ("lvl", 20_000, 60), ("lvl", 50_000, 120), ("lvl", 100_000, 240), ("lvl", 300_000, 300)]
    exits = [(2, 0.5, 0.5, 0.35), (3, 0.34, 0.5, 0.40), (2, 0.5, 0.0, 0.40), (5, 0.2, 0.6, 0.40), (1.5, 0.67, 0.3, 0.30)]
    best = []
    for tk in (1, 5, 20):
        for rule in rules:
            for ex in exits:
                res = {}
                for tag, sub in (("diseño", rows[:half]), ("prueba", rows[half:])):
                    E = entries(sub, rule, g)
                    pnl = [x for x in (trade(r, b, tk, *ex, g=g) for r, b in E) if x is not None]
                    if len(pnl) < 20:
                        res[tag] = None; continue
                    roi = [p / tk for p in pnl]
                    res[tag] = {"n": len(roi), "media": st.mean(roi), "acierto": sum(x > 0 for x in roi) / len(roi),
                                "t": st.mean(roi) / (st.pstdev(roi) / math.sqrt(len(roi)) or 1e-9), "p90": sorted(roi)[int(.9 * len(roi))],
                                "max": max(roi)}
                if res.get("diseño") and res.get("prueba"):
                    best.append((tk, rule, ex, res))
    best.sort(key=lambda b: -b[3]["diseño"]["media"])
    print("ticket  regla de entrada          salida (recupera a / vende / stop / trail)   diseño: n media acierto t  |  prueba: n media acierto t")
    for tk, rule, ex, res in best[:25]:
        d, p = res["diseño"], res["prueba"]
        print(f" ${tk:<4} {str(rule):26s} {str(ex):34s}  {d['n']:5d} {d['media']:+6.1%} {d['acierto']:4.0%} {d['t']:+5.1f} | {p['n']:5d} {p['media']:+6.1%} {p['acierto']:4.0%} {p['t']:+5.1f}")
    return best


def montecarlo(rows, rule, ex, tk, N, sims=4000, g="g1", seed=3):
    """Distribución del resultado de una canasta de N entradas con la regla (sobre toda la muestra)."""
    E = entries(rows, rule, g)
    pnl = [x for x in (trade(r, b, tk, *ex, g=g) for r, b in E) if x is not None]
    rng = random.Random(seed); out = []
    for _ in range(sims):
        s = sum(rng.choice(pnl) for _ in range(N)); out.append(s / (N * tk))
    out.sort()
    return {"N": N, "p_ganar": sum(x > 0 for x in out) / sims, "p10": out[sims // 10], "mediana": out[sims // 2], "p90": out[9 * sims // 10], "media": st.mean(out)}


def martingale(rows, rule, ex, base, cap_mult=32, g="g1", seed=5):
    """Escalar el ticket tras cada pérdida (x2) hasta recuperar; vuelve a la base al ganar. Mide ruina y resultado."""
    E = entries(rows, rule, g)
    rng = random.Random(seed); res = []
    for _ in range(2000):
        bank, tk, worst = 0.0, base, 0.0
        for _ in range(200):
            r, b = rng.choice(E)
            p = trade(r, b, tk, *ex, g=g)
            if p is None:
                continue
            bank += p; worst = min(worst, bank)
            tk = base if p > 0 else min(tk * 2, base * cap_mult)
        res.append((bank, worst))
    res.sort()
    return {"media": st.mean(b for b, _ in res), "p_ganar": sum(b > 0 for b, _ in res) / len(res), "peor_caida_mediana": sorted(w for _, w in res)[len(res) // 2]}


def main(d="state/research/censo"):
    rows, tot = load(d)
    if tot:
        agg = defaultdict(lambda: [0, 0])
        for t in tot:
            agg[t["s"]][0] += t.get("total") or 0; agg[t["s"]][1] += 1
        print("lanzamientos por hora (total de la API): " + "  ".join(f"{s}: {v[0]/max(v[1],1):.0f}/h" for s, v in sorted(agg.items())))
    for s in "ABC":
        if s in rows:
            life(rows[s], s)
    if "C" in rows and rows["C"] and "g5" in rows["C"][0]:
        life(rows["C"], "C (48 h, velas 5m)", g="g5", step_min=5)
    for s in "BC":
        if s in rows:
            ladder(rows[s], s)
    if "C" in rows and rows["C"] and "g5" in rows["C"][0]:
        ladder(rows["C"], "C (48 h)", g="g5", step_min=5)
    if "A" in rows:
        baskets(rows["A"], "A (todos los lanzamientos, sin sesgo)")
    if "B" in rows:
        best = baskets(rows["B"], "B (>=40 compras AL FINAL: sesgo hacia las que arrancaron)")
        print("\nMonte Carlo de canastas (mejor regla del diseño, toda la muestra):")
        if best:
            tk, rule, ex, _ = best[0]
            for N in (10, 20, 30, 50, 100):
                print("  ", montecarlo(rows["B"], rule, ex, tk, N))
            print("Escalar el ticket tras perder (x2, tope 32x):", martingale(rows["B"], rule, ex, tk))
    if "C" in rows:
        baskets(rows["C"], "C (>=1000 compras, sesgado a ganadoras: solo para escalones altos)")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or []))
