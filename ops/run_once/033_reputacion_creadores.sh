#!/bin/bash
# Etapa 1 del sniper selectivo: reputación de creadores con los lanzamientos ya bajados, y qué habría dado
# comprar en el primer minuto (precio de la primera vela) y vender al minuto 1-2.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, time, statistics as st
from collections import defaultdict
from pathlib import Path
from fomo_intel.launches import LaunchFetcher
from fomo_intel.backtest.entrysim import SimParams, simulate
lf = LaunchFetcher("x", "data"); L = [l for l in lf.load_all() if l.deployer and l.created_ts > 0]
print("lanzamientos con creador:", len(L), "; graduados:", sum(l.graduated for l in L))
by_dev = defaultdict(list)
for l in L: by_dev[l.deployer].append(l)
multi = {d: ls for d, ls in by_dev.items() if len(ls) >= 2}
print("creadores:", len(by_dev), "; con >=2 lanzamientos en la muestra:", len(multi), "; con >=3:", sum(1 for ls in multi.values() if len(ls) >= 3))
# distribución de tasa de graduación entre creadores con >=3
rates = sorted(((sum(x.graduated for x in ls)/len(ls), len(ls), d) for d, ls in multi.items() if len(ls) >= 3), reverse=True)
print("top creadores por tasa de graduación (tasa, n, wallet):"); [print("  ", round(r,2), n, d[:10]) for r, n, d in rates[:15]]
# ¿sirve la historia del creador? Para cada lanzamiento, mirar la historia PREVIA del creador (solo tokens anteriores) y el resultado de ESTE.
L.sort(key=lambda l: l.created_ts)
hist = defaultdict(lambda: {"n": 0, "g": 0})
rows = []
charts = {}
for l in L:
    h = hist[l.deployer]; prior_n, prior_g = h["n"], h["g"]
    cp = Path(f"data/charts/{l.mint}.json")
    c = json.load(open(cp))["candles"] if cp.exists() else None
    if c and len(c) >= 3:
        # sniper: entra al OPEN de la primera vela (~segundo 1-10) con 5% slippage+fee; vende a: cierre min1, cierre min2, o TP+80%/stop-40% en 3 min
        o = c[0]["o"]
        if o > 0:
            entry = o * 1.05
            r1 = c[1]["c"] / entry - 1 if len(c) > 1 else None
            r2 = c[2]["c"] / entry - 1 if len(c) > 2 else None
            s = simulate(l.mint, l.symbol, l.created_ts, c, SimParams(entry_min=0, max_wait_min=1, fill="open", stop_fill="close", tp_levels=((1.8, 1.0),), trail=0.5, stop=0.4, max_hold_min=3))
            rows.append({"dev": l.deployer, "prior_n": prior_n, "prior_g": prior_g, "grad": l.graduated, "r1": r1, "r2": r2, "r_tp": s.ret if s.entered else None, "ts": l.created_ts, "sym": l.symbol})
    h["n"] += 1; h["g"] += int(l.graduated)
print("\nlanzamientos con velas desde el minuto 0:", len(rows))
def desc(name, g):
    g = [x for x in g if x["r_tp"] is not None]
    if len(g) < 10: print(f"{name:<40} n={len(g)} (poca muestra)"); return
    for k in ("r1", "r2", "r_tp"):
        v = [x[k] for x in g if x[k] is not None]
        w = sum(1 for z in v if z > 0)/len(v)
        print(f"{name:<40} {k:>4}: n={len(v):4d} acierto={w:.0%} ret/op={sum(v)/len(v):+.2f} mediana={st.median(v):+.2f}")
desc("todos", rows)
desc("creador sin historia previa", [x for x in rows if x["prior_n"] == 0])
desc("creador con >=1 lanz. previo", [x for x in rows if x["prior_n"] >= 1])
desc("creador con >=1 graduado previo", [x for x in rows if x["prior_g"] >= 1])
desc("creador con >=2 graduados previos", [x for x in rows if x["prior_g"] >= 2])
desc("creador con >=2 previos y 0 graduados", [x for x in rows if x["prior_n"] >= 2 and x["prior_g"] == 0])
# graduación de ESTE token según historia previa
for name, sel in (("sin historia", lambda x: x["prior_n"] == 0), (">=1 grad previo", lambda x: x["prior_g"] >= 1), (">=2 grad previos", lambda x: x["prior_g"] >= 2), (">=2 previos sin grad", lambda x: x["prior_n"] >= 2 and x["prior_g"] == 0)):
    g = [x for x in rows if sel(x)]
    if g: print(f"graduación de este token | {name:<22}: {sum(x['grad'] for x in g)/len(g):.0%} (n={len(g)})")
print("\nOJO: la muestra viene en gran parte de listas de graduados (sesgo); sirve para comparar grupos, no para la tasa absoluta.")
PY
