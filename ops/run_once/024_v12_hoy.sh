#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, time
from pathlib import Path
from fomo_intel.backtest.entrysim import SimParams, simulate
from fomo_intel.backtest.rules import V1, RULESETS
log = json.load(open("data/validation.json")); charts = Path("data/charts")
fn, entry_min, tol = RULESETS["v1.2"]
ops = [(m, v) for m, v in log.items() if v["rules"].get("v1.2", {}).get("entro") and v.get("final")]
for fill in ("level", "close"):
    rows = []
    for m, v in ops:
        cp = charts / f"{m}.json"
        if not cp.exists(): continue
        r = simulate(m, v["symbol"], v["created_ts"], json.load(open(cp))["candles"], SimParams(entry_min=entry_min, fill="close", stop_fill=fill, **V1["exit"]))
        if r.entered: rows.append((v["created_ts"], v["symbol"], r.ret, [e[3] for e in r.exits]))
    rows.sort()
    w = sum(1 for r in rows if r[2] > 0); acum = 0; curva = []
    for r in rows: acum += r[2]; curva.append(round(acum, 2))
    print(f"[stop {fill:<5}] ops={len(rows)} aciertos={w}/{len(rows)} ({w/len(rows):.0%}) total={sum(r[2] for r in rows):+.2f} por US$1 ; mediana ret={sorted(r[2] for r in rows)[len(rows)//2]:+.2f}")
    print("   curva acumulada:", curva)
    if fill == "close":
        for r in rows: print("   ", time.strftime("%d/%m %H:%M", time.gmtime(r[0])), f"{r[1]:>10} {r[2]:+.2f} {r[3]}")
PY
