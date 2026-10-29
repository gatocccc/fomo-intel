#!/bin/bash
# Nonco Genesis no implementa totalSupply (revierte). Usar totalMinted()/canvasMinted()/legacyMinted() y probar balanceOf con minters reales.
cd /root/fomo_intel
python3 - <<'PY'
import requests, json
C="0x79121e9ffa0390c617da70cad6d11610856a7d18"
RPCS=["https://ethereum-rpc.publicnode.com","https://eth.llamarpc.com","https://1rpc.io/eth","https://eth.drpc.org"]
def call(m,p):
    last=None
    for u in RPCS:
        try:
            r=requests.post(u,json={"jsonrpc":"2.0","id":1,"method":m,"params":p},timeout=25).json()
            if "result" in r: return r["result"]
            last=r.get("error")
        except Exception as e: last=str(e)
    return {"error":last}
for sel,n in (("0xa2309ff8","totalMinted"),("0xb29df4e1","canvasMinted"),("0xf76f7003","legacyMinted"),("0x18160ddd","totalSupply (no existe)")):
    r=call("eth_call",[{"to":C,"data":sel},"latest"]); print(n,":", int(r,16) if isinstance(r,str) and r.startswith("0x") and len(r)>2 else r)
# minters: eventos Transfer desde 0x0, por tramos chicos
T="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"; Z="0x"+"0"*64
latest=int(call("eth_blockNumber",[]),16)
owners={}; frm=latest-300000; got=0
while frm<latest:
    to=min(frm+2000,latest)
    r=call("eth_getLogs",[{"fromBlock":hex(frm),"toBlock":hex(to),"address":C,"topics":[T,Z]}])
    if isinstance(r,list):
        got+=1
        for l in r: o="0x"+l["topics"][2][-40:]; owners[o]=owners.get(o,0)+1
    frm=to+1
print("tramos leídos",got,"mints vistos",sum(owners.values()),"billeteras",len(owners))
for o,n in list(sorted(owners.items(),key=lambda x:-x[1]))[:5]:
    b=call("eth_call",[{"to":C,"data":"0x70a08231"+o[2:].rjust(64,"0")},"latest"])
    print(" ",o,"minteó",n,"-> balanceOf",int(b,16) if isinstance(b,str) else b)
# y lo que hace la app con esa billetera (count_ducks)
import sys; sys.path.insert(0,"."); 
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.app.server import count_ducks
if owners:
    top=max(owners,key=owners.get); print("count_ducks(app) para",top,"=",count_ducks(top))
PY
