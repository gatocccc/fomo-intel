#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import base64, os, requests, struct
from fomo_intel.live.helius_watch import _b58
rpc = f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
tx = "5M2rpQ5H3AmRtT4NRS9ueAkzzwaEW4D2AzGBbcUucyRpRzCKWNX1pKQWwpM4Y8xfQG9azi6orHtVbCpJCuYVpCoV"
r = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx, {"encoding": "json", "maxSupportedTransactionVersion": 1}]}, timeout=30).json()["result"]
for l in r["meta"]["logMessages"]:
    if l.startswith("Program data: "):
        b = base64.b64decode(l[14:]); print("blob len", len(b), "disc", b[:8].hex(), "b[8:40]", _b58(b[8:40])[:12] if len(b) >= 40 else "")
    elif "Instruction:" in l or "invoke" in l: print("  ", l[:110])
print("cantidad de logs:", len(r["meta"]["logMessages"]), "| truncado:", any("Log truncated" in l for l in r["meta"]["logMessages"]))
PY
