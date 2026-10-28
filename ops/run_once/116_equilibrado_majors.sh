#!/bin/bash
# Equilibrado: memecoins medianas y grandes conocidas, tendencia (promedio 20 días) y volumen; estado de GTA6.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import os, time, requests
H={"x-api-key":os.environ["SOLANATRACKER_API_KEY"]}; B="https://data.solanatracker.io"; now=int(time.time())
def get(p,**q):
    try: return requests.get(B+p,headers=H,params=q,timeout=30).json()
    except Exception: return {}
names=["BONK","WIF","POPCAT","FARTCOIN","PENGU","MEW","GOAT","PNUT","MOODENG","CHILLGUY","GIGA","USELESS","SPX","AI16Z","ZEREBRO","MOTHER","RETARDIO","MICHI","BOME","SLERF","PONKE","WEN","TRUMP","ANSEM","STONK","TROLL","LAUNCHCOIN","PUMP"]
seen={}
for n in names:
    d=get("/search",query=n,sortBy="liquidityUsd",sortOrder="desc",limit=3)
    for x in (d.get("data") or [])[:1]:
        if (x.get("symbol") or "").upper()==n: seen[n]=x
for n,x in seen.items():
    m=x["mint"]; cs=(get(f"/chart/{m}",type="1d",time_from=now-40*86400,time_to=now) or {}).get("oclhv",[])
    cl=[float(c["close"]) for c in cs]; vol=[float(c.get("volume") or 0) for c in cs]
    if len(cl)<21: continue
    ma20=sum(cl[-21:-1])/20; mc=x.get("marketCapUsd") or 0; liq=x.get("liquidityUsd") or 0
    print(f"{n:10s} mcap ${mc/1e6:7.1f}M liq ${liq/1e6:5.2f}M vol1d ${vol[-1]/1e6:6.2f}M | vs ma20 {cl[-1]/ma20-1:+6.1%} | 1d {cl[-1]/cl[-2]-1:+6.1%} 7d {cl[-1]/cl[-8]-1:+6.1%} 30d {cl[-1]/cl[-31]-1 if len(cl)>31 else 0:+6.1%} | {m}")
print()
for m in ["4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"]:
    d=get(f"/tokens/{m}"); p=(d.get("pools") or [{}])[0]; e=d.get("events",{})
    print("GTA6 mcap",round(p.get("marketCap",{}).get("usd",0)),"liq",round(p.get("liquidity",{}).get("usd",0)),"holders",d.get("holders"),{k:round(v.get("priceChangePercentage",0),1) for k,v in e.items()})
PY
