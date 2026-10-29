#!/bin/bash
# Chequeo rápido pedido por Gastón 29/10 18:32: token "funds are safu" (narrativa del hack/outflows de Binance).
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import os, json, time, requests
H={"x-api-key": os.getenv("SOLANATRACKER_API_KEY","")}; B="https://data.solanatracker.io"
seen=set(); rows=[]
for q in ("funds are safu","safu","SAFU"):
    r=requests.get(B+"/search",headers=H,params={"query":q,"sortBy":"liquidityUsd","sortOrder":"desc","limit":10},timeout=30)
    for x in (r.json().get("data") or []):
        if x["mint"] in seen: continue
        seen.add(x["mint"]); rows.append(x)
rows.sort(key=lambda x:-(x.get("liquidityUsd") or 0))
now=time.time()
for x in rows[:10]:
    age_h=(now-(x.get("createdAt") or now*1000)/1000)/3600 if x.get("createdAt") else None
    print(f"{x.get('symbol'):>12} | {x.get('name','')[:28]:28} | {x['mint']} | mcap {x.get('marketCapUsd',0):>10,.0f} | liq {x.get('liquidityUsd',0):>9,.0f} | vol24 {x.get('volume_24h',0) or 0:>10,.0f} | holders {x.get('holders')} | age {age_h and round(age_h,1)}h | 24h {x.get('priceChange24h')} | market {x.get('market')}")
print("--- detalle del mejor por liquidez")
if rows:
    m=rows[0]["mint"]
    d=requests.get(B+f"/tokens/{m}",headers=H,timeout=30).json()
    t=d.get("token",{}); p=(d.get("pools") or [{}])[0]; rk=d.get("risk",{})
    print(json.dumps({"name":t.get("name"),"symbol":t.get("symbol"),"mint":m,"created":t.get("creation",{}),"twitter":t.get("twitter"),"website":t.get("website"),"telegram":t.get("telegram"),
        "mcap":p.get("marketCap",{}).get("usd"),"liq":p.get("liquidity",{}).get("usd"),"market":p.get("market"),"lpBurn":p.get("lpBurn"),
        "risk":{"score":rk.get("score"),"rugged":rk.get("rugged"),"top10":rk.get("top10"),"snipers":(rk.get("snipers") or {}).get("totalPercentage"),"insiders":(rk.get("insiders") or {}).get("totalPercentage"),"bundlers":(rk.get("bundlers") or {}).get("totalPercentage"),"risks":[r.get("name") for r in rk.get("risks",[])]},
        "holders":d.get("holders"),"buys24":d.get("buys"),"sells24":d.get("sells"),"txns":d.get("txns"),"events":{k:v.get("priceChangePercentage") for k,v in (d.get("events") or {}).items() if k in ("1h","6h","24h")}},indent=1,default=str)[:2500])
    print("--- anti-rug (dd)")
    os.system(f"timeout 240 python3 -m fomo_intel.desk.dd {m} 2>&1 | tail -25")
PY
