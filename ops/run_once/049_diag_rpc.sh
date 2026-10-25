#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 200 python3 -u - <<'PY'
import json, os, requests
tx = "24YTARWpvxS21kg7Ha4Jp2pq8seP8kK57GyZb2WGeEgiFgJUTuusKWvKfkcaHeYGQVgRDJBVWPrz7Ja7jAZPkFSE"
for name, url in (("helius", f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"), ("publico", "https://api.mainnet-beta.solana.com")):
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]}, timeout=30)
    print(name, r.status_code, r.text[:300])
    if r.ok and (r.json().get("result")):
        res = r.json()["result"]; keys = res["transaction"]["message"]["accountKeys"]
        print("   firmantes:", [k["pubkey"] for k in keys if k.get("signer")])
        print("   instrucciones:", [l for l in res["meta"]["logMessages"] if "Instruction:" in l][:6])
r = requests.post(f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}", json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": ["B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC"]}, timeout=20)
print("helius getBalance:", r.status_code, r.text[:200])
PY
