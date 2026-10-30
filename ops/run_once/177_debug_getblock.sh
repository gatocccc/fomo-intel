#!/bin/bash
# 30/10 — la auditoría 176 no pudo leer bloques (getBlock). Diagnóstico: qué devuelve Helius para un slot de una compra nuestra.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
python3 - <<'PY'
import os, requests, json, time
RPC=f"https://mainnet.helius-rpc.com/?api-key={os.environ.get('HELIUS_API_KEY','')}"
for det, enc in (("accounts","json"),("accounts","jsonParsed"),("signatures","json")):
    t=time.time()
    try:
        r=requests.post(RPC,json={"jsonrpc":"2.0","id":1,"method":"getBlock","params":[463029493,{"encoding":enc,"transactionDetails":det,"maxSupportedTransactionVersion":0,"rewards":False,"commitment":"confirmed"}]},timeout=90)
        j=r.json(); res=j.get("result")
        print(det,enc,r.status_code,round(time.time()-t,1),"s", "err:",j.get("error"), "ntx:", len((res or {}).get("transactions") or (res or {}).get("signatures") or []), "bytes", len(r.content))
        if res and det=="accounts": print(json.dumps(res["transactions"][0])[:600])
    except Exception as e: print(det,enc,"EXC",e, round(time.time()-t,1))
PY
