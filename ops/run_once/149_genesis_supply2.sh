#!/bin/bash
cd /root/fomo_intel
set -a; . ./.env; set +a
C=0x79121e9ffa0390c617da70cad6d11610856a7d18
RPC="${ETH_RPC_URL:-https://eth.llamarpc.com}"
python3 - "$C" "$RPC" <<'PY'
import sys, requests
c, rpc = sys.argv[1], sys.argv[2]
def call(m,p):
    for u in (rpc, "https://eth.llamarpc.com", "https://rpc.ankr.com/eth", "https://1rpc.io/eth", "https://cloudflare-eth.com"):
        try:
            r=requests.post(u,json={"jsonrpc":"2.0","id":1,"method":m,"params":p},timeout=30).json()
            if "result" in r: return r["result"], u
        except Exception as e: pass
    return None, None
T="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
latest,u=call("eth_blockNumber",[]); latest=int(latest,16); print("rpc",u,"block",latest)
# todos los Transfer del contrato en bloques de 10k, últimos ~60 días (430k bloques)
logs=[]; frm=latest-430000
while frm<latest:
    to=min(frm+9999,latest)
    r,u=call("eth_getLogs",[{"fromBlock":hex(frm),"toBlock":hex(to),"address":c,"topics":[T]}])
    if r is None: print("sin logs en",frm); break
    logs+=r; frm=to+1
print("transfers:",len(logs))
mints=[l for l in logs if l["topics"][1]=="0x"+"0"*64]
print("mints:",len(mints))
own={}
for l in logs:
    o="0x"+l["topics"][2][-40:]; own[o]=own.get(o,0)+1
for o,n in list(sorted(own.items(),key=lambda x:-x[1]))[:5]:
    b,_=call("eth_call",[{"to":c,"data":"0x70a08231"+o[2:].rjust(64,"0")},"latest"]); print(" ",o,"recibió",n,"balanceOf",int(b,16) if b else None)
for sel,name in (("0x18160ddd","totalSupply"),("0x95d89b41","symbol")):
    b,_=call("eth_call",[{"to":c,"data":sel},"latest"]); print(name, b[:80] if b else None)
PY
