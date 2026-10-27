#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 120 python3 - <<'PY'
import os, requests, time, json
H={"x-api-key":os.environ["SOLANATRACKER_API_KEY"]}; m="CA8q2mkYWZnUNqYmf6pxyxAPZsmSe2EG9P7hHMW5pump"
r=requests.get(f"https://data.solanatracker.io/tokens/{m}",headers=H,timeout=30).json()
t=r.get("token",{}); rk=r.get("risk",{})
print("name",t.get("name"),"| desc:",(t.get("description") or "")[:300]); print("socials:",t.get("twitter"),t.get("website"),t.get("telegram"),t.get("strictSocials"))
print("creator:",(t.get("creation") or {}).get("creator"),"| holders",r.get("holders"),"| risks",[x.get("name") for x in rk.get("risks",[])],"| dev%",(rk.get("dev") or {}).get("percentage"),"| snipers%",(rk.get("snipers") or {}).get("totalPercentage"),"| insiders%",(rk.get("insiders") or {}).get("totalPercentage"),"| bundlers%",(rk.get("bundlers") or {}).get("totalPercentage"))
now=int(time.time())
cs=requests.get(f"https://data.solanatracker.io/chart/{m}",headers=H,params={"type":"1h","time_from":now-5*86400,"time_to":now},timeout=30).json().get("oclhv",[])
hi=max(float(c["high"]) for c in cs); print("velas 1h:",len(cs),"| cierres como % del máx:",[round(float(c["close"])/hi*100) for c in cs][-48:]); print("vol US$K por hora:",[round(float(c.get("volume") or 0)/1e3) for c in cs][-48:])
h=requests.get(f"https://data.solanatracker.io/tokens/{m}/holders/top",headers=H,timeout=30).json()
print("top holders %:",[round(x.get("percentage",0),1) for x in (h if isinstance(h,list) else h.get("holders",[]))[:12]])
PY
