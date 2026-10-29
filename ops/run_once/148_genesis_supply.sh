#!/bin/bash
# ¿Cuántos Nonco Genesis hay minteados y quién tiene? Contamos eventos Transfer desde 0x0 (mints) y probamos balanceOf de los que mintearon.
cd /root/fomo_intel
set -a; . ./.env; set +a
C=0x79121e9ffa0390c617da70cad6d11610856a7d18
python3 - "$C" <<'PY'
import sys, json, requests
c=sys.argv[1]; rpc="https://ethereum-rpc.publicnode.com"
def call(m,p): return requests.post(rpc,json={"jsonrpc":"2.0","id":1,"method":m,"params":p},timeout=30).json()
T="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
Z="0x"+"0"*64
latest=int(call("eth_blockNumber",[])["result"],16)
mints=[]; frm=latest-700000
while frm<latest:
    to=min(frm+49999,latest)
    r=call("eth_getLogs",[{"fromBlock":hex(frm),"toBlock":hex(to),"address":c,"topics":[T,Z]}])
    if "error" in r: print("logs error",r["error"]); break
    mints+=r["result"]; frm=to+1
print("mints (Transfer desde 0x0) en ~100 días:",len(mints))
owners={}
for l in mints:
    o="0x"+l["topics"][2][-40:]; owners[o]=owners.get(o,0)+1
print("minters distintos:",len(owners))
for o,n in list(sorted(owners.items(),key=lambda x:-x[1]))[:5]:
    data="0x70a08231"+o[2:].rjust(64,"0")
    b=int(call("eth_call",[{"to":c,"data":data},"latest"]).get("result","0x0"),16)
    print(" ",o,"minteó",n,"tiene ahora",b)
PY
