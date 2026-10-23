#!/bin/bash
# Búsqueda de reglas de salida/entrada sobre los 318 lanzamientos históricos que se movieron 3x (stop realista).
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, itertools
from pathlib import Path
from fomo_intel.launches import LaunchFetcher
from fomo_intel.backtest.entrysim import SimParams, simulate
from fomo_intel.backtest.rules import base_price, entry_candle
rows = json.load(open("state/ops/rug_rows.json")); bysym = {r["sym"]: r for r in rows}
lf = LaunchFetcher("x", "data"); L = {l.mint: l for l in lf.load_all() if l.symbol in bysym and not l.partial}
charts = {m: json.load(open(f"data/charts/{m}.json"))["candles"] for m in L if Path(f"data/charts/{m}.json").exists()}
def v12(r): return r['n_early']>=40 and r['vol_early']>=2000 and r['vol_early']/max(1,r['n_early'])<=200 and r['snipers']>=1
sub = {m for m, l in L.items() if v12(bysym[l.symbol])}
res = []
for entry_min, tp, tpf, trail, stop, hold in itertools.product((1, 2, 3), (1.5, 2.0, 3.0), (0.5, 1.0), (0.15, 0.25, 0.35, 0.5), (0.2, 0.3, 0.4), (60, 360)):
    p = SimParams(entry_min=entry_min, fill="close", stop_fill="close", tp_levels=((tp, tpf),), trail=trail, stop=stop, max_hold_min=hold)
    for label, mints in (("todos", list(charts)), ("v1.2", [m for m in charts if m in sub])):
        rets = []
        for m in mints:
            r = simulate(m, L[m].symbol, L[m].created_ts, charts[m], p)
            if r.entered: rets.append(r.ret)
        if len(rets) >= 30:
            w = sum(1 for x in rets if x > 0) / len(rets)
            res.append((label, entry_min, tp, tpf, trail, stop, hold, len(rets), round(w, 3), round(sum(rets), 1), round(sum(rets) / len(rets), 3), round(min(rets), 2)))
for label in ("v1.2", "todos"):
    sel = sorted([r for r in res if r[0] == label], key=lambda r: (-r[10]))
    print(f"\n== {label}: mejores por retorno promedio por operación (entrada_min, tp, frac, trail, stop, hold_min, n, acierto, total, ret/op, peor)")
    for r in sel[:12]: print("  ", r[1:])
    sel = sorted([r for r in res if r[0] == label and r[10] > 0], key=lambda r: (-r[8]))
    print(f"== {label}: mejores por ACIERTO con retorno/op positivo")
    for r in sel[:12]: print("  ", r[1:])
PY
