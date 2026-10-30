#!/bin/bash
# 30/10 — complemento de 178: vuelca listas completas (holders/top traders/primeros) y quién es cada fondeador grande.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 300 python3 - <<'PY'
import os, json, requests
d=json.load(open("state/research/tygr_alts.json"))
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}; HK=os.environ.get("HELIUS_API_KEY","")
M=d["mint"]
h=requests.get(f"{ST}/tokens/{M}/holders",headers=SH,timeout=25).json()
print("HOLDERS", json.dumps([[a["wallet"],round(a["percentage"],2),round(a["value"]["usd"])] for a in h.get("accounts",[])]))
t=requests.get(f"{ST}/top-traders/{M}",headers=SH,timeout=25).json()
print("TRADERS", json.dumps([[x["wallet"],round(x.get("total_invested",0)),round(x.get("realized",0)),round(x.get("unrealized",0)),x.get("holding",0)>0] for x in t]))
print("EARLY", json.dumps(d["early"]))
r=requests.get(f"https://frontend-api-v3.pump.fun/users/{d['early'][0]}",timeout=20); print("PUMP users status", r.status_code, r.text[:150])
for f in ["5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9","F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe","B48kNVXs4YK4amkBCH2XokQiv1SeiVQGHDR17xDeKAAn"]:
    j=requests.get(f"https://api.helius.xyz/v1/wallet/{d['early'][0] if f.startswith('5tz') else f}/funded-by?api-key={HK}",timeout=20)
    print("FUNDED-BY", f, j.status_code, j.text[:300])
PY
