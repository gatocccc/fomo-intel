#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 200 python3 - <<'PY'
import os, requests, time
H={"x-api-key":os.environ["SOLANATRACKER_API_KEY"]}
C={"JEANPHIL":"9X7HpzDX6GKJo2xr1ygEFSeMGNdBwZr6Abc2qajBpump","DOAS":"2qPoPQQCHGtDbgdSxXfrzW1iRS3cGbKmMWSMapZ4pump","USDF":"9k6gfTLbDaUpx635kQaGTeDvzYs7hWdDW1MerpjYpump","USOE":"MXwaXV5KHX4j6TgcuLh2L37TAfcm7itL4nfHpeqpump"}
now=int(time.time())
for s,m in C.items():
    cs=requests.get(f"https://data.solanatracker.io/chart/{m}",headers=H,params={"type":"1h","time_from":now-6*86400,"time_to":now},timeout=30).json().get("oclhv",[])
    if not cs: print(s,"sin velas"); continue
    cl=[float(c["close"]) for c in cs]; hi=max(float(c["high"]) for c in cs); last=cl[-1]
    v=[round(float(c.get("volume") or 0)/1e3) for c in cs]
    print(f"{s}: {len(cs)} velas 1h | último {last:.3g} | máx 6d {hi:.3g} ({last/hi:.0%} del máx) | 6h {last/cl[-7]-1:+.0%} | 24h {last/cl[-25]-1 if len(cl)>25 else 0:+.0%} | 72h {last/cl[-73]-1 if len(cl)>73 else 0:+.0%}")
    print("   cierres últimas 24h (x1e-3 del máx):", [round(x/hi*100) for x in cl[-24:]])
    print("   volumen US$K últimas 24h:", v[-24:])
    r=requests.get(f"https://data.solanatracker.io/tokens/{m}",headers=H,timeout=30).json(); rk=r.get("risk") or {}
    print("   holders",r.get("holders"),"| riesgos:",[x.get("name") for x in rk.get("risks",[])][:6],"| dev %",(rk.get("dev") or {}).get("percentage"),"| snipers %",(rk.get("snipers") or {}).get("totalPercentage"),"| insiders %",(rk.get("insiders") or {}).get("totalPercentage"))
PY
