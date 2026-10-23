#!/bin/bash
# Recalcula las operaciones de v1.2 de la validación con el stop vendiendo al CIERRE de la vela (realista) vs al nivel (optimista).
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json
from pathlib import Path
from fomo_intel.backtest.entrysim import SimParams, simulate
from fomo_intel.backtest.rules import V1, RULESETS
log = json.load(open("data/validation.json"))
charts = Path("data/charts")
for name in ("v1.2", "v1.1", "v1"):
    fn, entry_min, tol = RULESETS[name]
    ops = [(m, v) for m, v in log.items() if v.get("rules", {}).get(name, {}).get("entro") and v.get("final")]
    for fill in ("level", "close"):
        rets = []
        rows = []
        for m, v in ops:
            cp = charts / f"{m}.json"
            if not cp.exists(): continue
            candles = json.load(open(cp))["candles"]
            r = simulate(m, v["symbol"], v["created_ts"], candles, SimParams(entry_min=entry_min, fill="close", stop_fill=fill, **V1["exit"]))
            if r.entered: rets.append(r.ret); rows.append((v["symbol"], round(r.ret, 2), [e[3] for e in r.exits]))
        if rets:
            w = sum(1 for x in rets if x > 0)
            print(f"[{name}] stop_fill={fill:<5} ops={len(rets)} aciertos={w/len(rets):.0%} total(US$1 c/u)={sum(rets):+.2f} peor={min(rets):+.2f}")
            if name == "v1.2": print("   ", rows)
PY
