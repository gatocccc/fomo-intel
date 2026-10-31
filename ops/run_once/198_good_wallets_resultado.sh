#!/bin/bash
# 30/10 — Resultado de ops 195 (billeteras buenas → consenso). Espera a que termine.
cd /root/fomo_intel || exit 1
for i in $(seq 1 56); do [ -f state/research/good_wallets.json ] && break; sleep 10; done
grep -v "calidad" state/research/good_wallets.log | cut -c1-400
python3 - <<'PY'
import json
try: d=json.load(open("state/research/good_wallets.json"))
except Exception as e: print("todavía no", e); raise SystemExit
print("billeteras",d["wallets"],"buenas",d["good"])
sk=sorted(((w,s) for w,s in d["skill"].items() if s.get("n",0)>=12), key=lambda x:-x[1]["mean_pct"])
print("top calidad:", [(w[:6],s["n"],s["mean_pct"],s.get("t"),s["buys_per_day"]) for w,s in sk[:8]])
print("mediana de compras/día buenas:", sorted(d["skill"][w]["buys_per_day"] for w in d["good_list"])[len(d["good_list"])//2] if d["good_list"] else None)
for k,v in d["tests"].items():
    print("\n##",k, {x:v.get(x) for x in ("events","with_prices")})
    for kk,vv in v.items():
        if isinstance(vv,dict): print(f"  {kk:24s}",vv)
PY
