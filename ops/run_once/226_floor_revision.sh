#!/bin/bash
# 31/10 17:35 — revisión de la lotería: (1) por qué el cierre de PEANUT no registró recuperación de renta; (2) en sombra: pico a 6 h de una muestra de candidatos elegibles.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 500 python3 - <<'PY'
import json, random, time, requests, os
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.live.config import Env
from fomo_intel.live.wallet import Rpc
rpc=Rpc(Env().rpc_url); W="HrRBytKRDJyhuYT9C5WAKs5jQ7ZRJPyZoQ3FRth2RXHK"
res=rpc.call("getTokenAccountsByOwner",[W,{"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},{"encoding":"jsonParsed"}]) or {}
res2=rpc.call("getTokenAccountsByOwner",[W,{"programId":"TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"},{"encoding":"jsonParsed"}]) or {}
accs=res.get("value",[])+res2.get("value",[])
z=[a for a in accs if int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])==0]
print("cuentas de token:",len(accs),"vacías:",len(z),"programas:",{a["account"]["owner"][:6] for a in accs})
pe=[a for a in accs if a["account"]["data"]["parsed"]["info"]["mint"].startswith("CvtdJdog")]
print("PEANUT:",[(a["pubkey"][:8],a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]) for a in pe])
# sombra
ST="https://data.solanatracker.io"; H={"x-api-key":os.environ["SOLANATRACKER_API_KEY"]}
c=[json.loads(l) for l in open("state/desk/floor_cands.jsonl")]
now=time.time(); old=[x for x in c if now-x["ts"]>6*3600+600]
random.seed(1); smp=random.sample(old,min(250,len(old)))
print("candidatos totales",len(c),"con 6 h cumplidas",len(old),"muestra",len(smp))
mults=[]
for x in smp:
    try:
        r=requests.get(f"{ST}/chart/{x['mint']}",params={"type":"1m","time_from":int(x["ts"]),"time_to":int(x["ts"]+6*3600)},headers=H,timeout=30).json()
        cs=r.get("oclhv") or []
        if not cs: mults.append((0,x)); continue
        e=cs[0]["open"] or cs[0]["close"]; pk=max(k["close"] for k in cs)
        mults.append((pk/e if e else 0,x))
    except Exception as ex: pass
    time.sleep(0.2)
mm=sorted([m for m,_ in mults],reverse=True)
print("pico de cierre / precio al ser candidato, muestra",len(mm),":"," ".join(f">={k}x {sum(m>=k for m in mm)}" for k in (1.5,2,3,5,10,30)))
print("mejores:",[(round(m,1),x["sym"]) for m,x in sorted(mults,key=lambda t:-t[0])[:8]])
PY
