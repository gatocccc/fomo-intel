#!/bin/bash
# Con el filtro "ninguna billetera tóxica" (reputación de la primera mitad), ¿qué salida gana más seguido en la segunda mitad?
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, itertools
from collections import defaultdict
from pathlib import Path
from fomo_intel.launches import LaunchFetcher
from fomo_intel.backtest.entrysim import SimParams, simulate
from fomo_intel.backtest.rules import base_price
lf = LaunchFetcher("x", "data"); L = [l for l in lf.load_all() if not l.partial and l.first_buyers]
toks = []
for l in L:
    cp = Path(f"data/charts/{l.mint}.json")
    if not cp.exists(): continue
    c = json.load(open(cp))["candles"]
    if not c or base_price(c) <= 0: continue
    early = {b.wallet for b in l.first_buyers if 0 <= b.first_trade_ts - l.created_ts <= 120 and not b.is_developer}
    toks.append({"mint": l.mint, "sym": l.symbol, "t0": l.created_ts, "c": c, "early": early})
toks.sort(key=lambda t: t["t0"]); half = len(toks)//2; train, test = toks[:half], toks[half:]
def rug_of(t):
    s = simulate(t["mint"], t["sym"], t["t0"], t["c"], SimParams(entry_min=1, fill="close", stop_fill="close"))
    return s.entered and (t["c"][-1]["c"] / s.entry_px < 0.15)
st = defaultdict(lambda: [0, 0])
for t in train:
    r = rug_of(t)
    for w in t["early"]: st[w][0] += 1; st[w][1] += r
for thr_n, thr_r in ((3, .6), (2, .5), (3, .5), (2, .67)):
    bad = {w for w, (n, r) in st.items() if n >= thr_n and r / n >= thr_r}
    clean = [t for t in test if not any(w in bad for w in t["early"])]
    print(f"\n== tóxicas: n>={thr_n} y rugs>={thr_r:.0%} -> {len(bad)} billeteras ; tokens de prueba sin tóxicas: {len(clean)} de {len(test)}")
    res = []
    for entry_min, tp, trail, stop, hold in itertools.product((1, 2), (1.3, 1.5, 2.0, 3.0), (0.15, 0.25, 0.35, 0.5), (0.25, 0.35, 0.5), (30, 120)):
        p = SimParams(entry_min=entry_min, fill="close", stop_fill="close", tp_levels=((tp, 1.0),), trail=trail, stop=stop, max_hold_min=hold)
        rets = [simulate(t["mint"], t["sym"], t["t0"], t["c"], p) for t in clean]
        rets = [r.ret for r in rets if r.entered]
        if len(rets) >= 20:
            res.append((round(sum(1 for x in rets if x > 0) / len(rets), 2), round(sum(rets) / len(rets), 3), len(rets), entry_min, tp, trail, stop, hold))
    res.sort(key=lambda r: (-r[0], -r[1]))
    print("   acierto, ret/op, n, entrada_min, tp(todo), trail, stop, hold_min")
    for r in res[:8]: print("  ", r)
    pos = sorted([r for r in res if r[1] > 0], key=lambda r: -r[0])
    print("   mejores con ret/op positivo:"); [print("  ", r) for r in pos[:6]]
PY
