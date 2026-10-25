#!/bin/bash
# ¿Quién firma la transacción de creación de los tokens de las fábricas? (PumpPortal informa el firmante como traderPublicKey)
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 300 python3 -u - <<'PY'
import json, os, requests
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
rpc = f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
cr = json.load(open("state/creators.json")) if os.path.exists("state/creators.json") else {}
print("creadores registrados en vivo desde el deploy:", len(cr))
for dev in json.load(open("state/factories.json"))["wallets"]:
    toks = (requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or [])
    toks.sort(key=lambda t: -(t.get("createdAt") or 0))
    for t in toks[:2]:
        info = requests.get(f"{B}/tokens/{t['mint']}", headers=h, timeout=30).json()
        tx = (info.get("token", {}).get("creation") or {}).get("created_tx")
        if not tx: print(dev[:8], t["mint"][:8], "sin created_tx"); continue
        r = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]}, timeout=30).json().get("result")
        if not r: print(dev[:8], t["mint"][:8], "tx no encontrada"); continue
        keys = r["transaction"]["message"]["accountKeys"]
        signers = [k["pubkey"] for k in keys if isinstance(k, dict) and k.get("signer")]
        print(f"{dev[:8]} mint {t['mint'][:8]} firmantes: {[s[:8] for s in signers]} | fábrica entre firmantes: {dev in signers} | fábrica entre cuentas: {dev in [k['pubkey'] if isinstance(k, dict) else k for k in keys]}")
    print("   vistos en vivo con ese creador:", len(cr.get(dev, [])))
PY
