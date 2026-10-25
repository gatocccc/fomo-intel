#!/bin/bash
# Helius recibió 118 notificaciones de las fábricas y no parseó ninguna. ¿Hubo lanzamientos? ¿parse_create los reconoce?
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 300 python3 -u - <<'PY'
import json, os, requests, time
from fomo_intel.live.helius_watch import parse_create, parse_swap
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
rpc = f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
cr = json.load(open("state/creators.json")) if os.path.exists("state/creators.json") else {}
def rpcc(m, p): return requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=30).json().get("result")
for dev in json.load(open("state/factories.json"))["wallets"]:
    toks = (requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or [])
    rec = [t for t in toks if now - (t.get("createdAt") or 0)/1000 < 3*3600]
    print(f"\n{dev[:8]} lanzamientos últimas 3 h (ST): {len(rec)} | vistos en vivo (creators.json): {len(cr.get(dev, []))}")
    # últimas firmas de la billetera y qué son
    sigs = rpcc("getSignaturesForAddress", [dev, {"limit": 8}]) or []
    for s in sigs[:6]:
        tx = rpcc("getTransaction", [s["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}])
        if not tx: print("   ", s["signature"][:10], "sin tx"); continue
        logs = " ".join((tx.get("meta") or {}).get("logMessages") or [])
        kinds = [k for k in ("Instruction: Create", "Instruction: CreateV2", "Instruction: Buy", "Instruction: Sell", "Transfer", "InitializeMint") if k in logs]
        progs = sorted({ix.get("programId", "")[:6] for ix in tx["transaction"]["message"].get("instructions", [])})
        print("   ", s["signature"][:10], "hace", round((now - (s.get("blockTime") or now))/60), "min |", kinds, "| progs", progs, "| create:", parse_create(tx, dev), "| swap:", bool(parse_swap(tx, dev)))
PY
