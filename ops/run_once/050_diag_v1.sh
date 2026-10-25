#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 200 python3 -u - <<'PY'
import json, os, requests
from fomo_intel.live.helius_watch import parse_create
rpc = f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
cases = {"24YTARWpvxS21kg7Ha4Jp2pq8seP8kK57GyZb2WGeEgiFgJUTuusKWvKfkcaHeYGQVgRDJBVWPrz7Ja7jAZPkFSE": "B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC",
         "5M2rpQ5H3AmRtT4NRS9ueAkzzwaEW4D2AzGBbcUucyRpRzCKWNX1pKQWwpM4Y8xfQG9azi6orHtVbCpJCuYVpCoV": "gVDXhoGbePACvSqN7CZBtQXFW9eyJwsgudPEwSydAkx"}
for tx, dev in cases.items():
    r = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}]}, timeout=30).json()
    res = r.get("result")
    if not res: print("sin resultado:", str(r)[:200]); continue
    keys = res["transaction"]["message"]["accountKeys"]
    print("versión:", res.get("version"), "| firmantes:", [k["pubkey"][:8] for k in keys if k.get("signer")], "| fábrica firma:", dev in [k["pubkey"] for k in keys if k.get("signer")])
    print("   instrucciones:", [l for l in res["meta"]["logMessages"] if "Instruction:" in l][:6])
    print("   parse_create:", parse_create(res, dev))
PY
python3 -c "import solders; print('solders', solders.__version__)"
python3 - <<'PY'
# ¿solders puede deserializar/firmar transacciones v1?
try:
    from solders.transaction import VersionedTransaction
    from solders.message import MessageV0
    print("VersionedTransaction ok; atributos de mensaje:", [a for a in dir(__import__('solders.message', fromlist=['x'])) if 'Message' in a])
except Exception as e: print("error", e)
PY
