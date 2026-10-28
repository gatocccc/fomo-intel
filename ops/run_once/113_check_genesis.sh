#!/bin/bash
# Verifica los contratos de Nonco Genesis cargados: nombre, símbolo, supply y que balanceOf responda.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import os, requests
rpc = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
def call(to, data):
    return requests.post(rpc, json={"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":to,"data":data},"latest"]}, timeout=15).json()
def s(h):
    try:
        b = bytes.fromhex(h[2:]); n = int.from_bytes(b[32:64], "big"); return b[64:64+n].decode()
    except Exception: return h[:80]
cs = [c.strip() for c in os.getenv("NONCO_CONTRACTS","").split(",") if c.strip()]
print("contratos:", cs)
for c in cs:
    code = requests.post(rpc, json={"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":[c,"latest"]}, timeout=15).json().get("result","")
    print(c, "tiene código:", len(code) > 2)
    print("  name", s(call(c, "0x06fdde03").get("result","0x")), "| symbol", s(call(c, "0x95d89b41").get("result","0x")))
    ts = call(c, "0x18160ddd"); print("  totalSupply", int(ts["result"],16) if ts.get("result") not in (None,"0x") else ts)
    b = call(c, "0x70a08231" + "0"*64); print("  balanceOf responde:", "result" in b, b.get("error"))
PY
