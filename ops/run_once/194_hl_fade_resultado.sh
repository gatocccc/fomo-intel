#!/bin/bash
# 30/10 — Resultado de ops 193 (ir en contra del top). Espera a que termine.
cd /root/fomo_intel || exit 1
for i in $(seq 1 56); do [ -f state/research/hl_fade.json ] && break; sleep 10; done
grep -v '^  ' state/research/hl_fade.log | head -5; grep "útiles\|corto" state/research/hl_fade.log | tail -3
python3 - <<'PY'
import json
try: d=json.load(open("state/research/hl_fade.json"))
except Exception as e: print("todavía no", e); raise SystemExit
print("pool",d["pool"],"útiles",d["usable"])
for c in d["cohorts"]:
    print("\n##",c["cohort"])
    for k,v in c.items():
        if k!="cohort": print(f"  {k:34s}", {x:v.get(x) for x in ("traders","n","mean_pct","win_pct","traders_positive_pct","mean_of_traders_pct","t_by_trader")})
PY
