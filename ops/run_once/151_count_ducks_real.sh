#!/bin/bash
cd /root/fomo_intel
python3 - <<'PY'
import requests, sys
sys.path.insert(0,".")
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.app.server import count_ducks, nonco_contracts
C="0x79121e9ffa0390c617da70cad6d11610856a7d18"
def call(d):
    for u in ("https://ethereum-rpc.publicnode.com","https://eth.llamarpc.com","https://1rpc.io/eth"):
        try:
            r=requests.post(u,json={"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":C,"data":d},"latest"]},timeout=20).json()
            if "result" in r: return r["result"]
        except Exception: pass
print("contratos en la app:", nonco_contracts())
for tid in (1,2,3,500,900):
    o=call("0x6352211e"+hex(tid)[2:].rjust(64,"0"))
    if not o or len(o)<42: print(tid,"sin dueño",o); continue
    owner="0x"+o[-40:]
    print(f"token #{tid} dueño {owner} -> count_ducks = {count_ducks(owner)}")
print("billetera sin patos ->", count_ducks("0x000000000000000000000000000000000000dEaD"))
PY
