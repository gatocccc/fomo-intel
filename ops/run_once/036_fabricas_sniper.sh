#!/bin/bash
# Creadores "fábrica" con alta tasa de graduación: ¿qué da comprar en el segundo 1 de SUS lanzamientos y vender al minuto 1-2?
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, os, requests, time, statistics as st, random
from fomo_intel.charts import ChartFetcher
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
devs = json.load(open("state/ops/creadores_st.json"))
top = [d for d in devs if d.get("rate") and d["rate"] >= 0.12 and (d.get("mcap_med") or 0) > 1000 and d["total"] >= 100]
print("fábricas con tasa >=12% (últimos 500) y actividad:", [(d["dev"][:8], d["rate"], d["total_api"]) for d in top])
cf = ChartFetcher(os.environ["SOLANATRACKER_API_KEY"], "data", sleep_s=0.0)
results = {}
for d in top[:6]:
    dev = d["dev"]
    try:
        r = requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json(); toks = r.get("data") or []
    except Exception as e: print(dev[:8], "err", e); continue
    toks = [t for t in toks if (t.get("createdAt") or 0) and now - t["createdAt"]/1000 > 3*3600]   # ya maduros
    random.seed(1); sample = random.sample(toks, min(40, len(toks)))
    rows = []
    for t in sample:
        mint = t["mint"]; created = int(t["createdAt"]/1000)
        try: c = cf.fetch(mint, created, hours=1.0, force=True)
        except Exception as e: continue
        if len(c) < 2 or c[0]["o"] <= 0: continue
        entry = c[0]["o"] * 1.05
        mx = max(x["h"] for x in c[:3]) / entry
        r1 = c[1]["c"]/entry - 1 if len(c) > 1 else None; r2 = c[2]["c"]/entry - 1 if len(c) > 2 else None
        r5 = (c[min(5, len(c)-1)]["c"]/entry - 1)
        grad = (t.get("market") or "").lower() not in ("pumpfun", "pumpfun-curve", "pump", "")
        rows.append({"sym": t.get("symbol"), "r1": r1, "r2": r2, "r5": r5, "max3": mx, "grad": grad, "n_candles": len(c), "mcap_now": t.get("marketCapUsd")})
    results[dev] = rows
    def s(k):
        v = [x[k] for x in rows if x[k] is not None]
        return f"{k}: acierto {sum(1 for z in v if z>0)/len(v):.0%} mediana {st.median(v):+.2f} prom {sum(v)/len(v):+.2f}" if v else f"{k}: -"
    print(f"\n{dev[:10]}… tasa API {d['rate']} total {d['total_api']} | muestra con velas: {len(rows)} | graduados en muestra: {sum(x['grad'] for x in rows)}")
    print("   ", s("r1"), "|", s("r2"), "|", s("r5"))
    if rows: print("    max en 3 min >=1.5x:", f"{sum(1 for x in rows if x['max3']>=1.5)/len(rows):.0%}", " >=2x:", f"{sum(1 for x in rows if x['max3']>=2)/len(rows):.0%}")
json.dump(results, open("state/ops/fabricas_sniper.json", "w"))
print("\nrequests usados:", cf.requests_made)
PY
