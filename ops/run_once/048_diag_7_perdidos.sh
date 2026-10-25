#!/bin/bash
# Los 7 lanzamientos perdidos: ¿quién firmó? ¿qué programa? ¿por qué no los vio ni PumpPortal ni Helius?
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 280 python3 -u - <<'PY'
import json, os, requests
from fomo_intel.live.helius_watch import parse_create
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
rpc = f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
cr = json.load(open("state/creators.json"))
mints = ["rjALAN7kNC", "72UuvWnASE", "4NWSwmboxz", "845H1SBkHq", "6xJjoz78HU", "94ZpC3Zxaz", "9AmNJ7sLSa"]
start = json.load(open("state/session.json"))["start"]
full = {}
for dev in json.load(open("state/factories.json"))["wallets"]:
    for t in (requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or []):
        if any(t["mint"].startswith(m) for m in mints): full[t["mint"]] = dev
for mint, dev in full.items():
    info = requests.get(f"{B}/tokens/{mint}", headers=h, timeout=30).json()
    cre = (info.get("token") or {}).get("creation") or {}
    tx = cre.get("created_tx")
    r = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]}, timeout=30).json().get("result") if tx else None
    if not r: print(mint[:8], "sin tx", tx); continue
    keys = r["transaction"]["message"]["accountKeys"]
    signers = [k["pubkey"] for k in keys if k.get("signer")]
    logs = r["meta"].get("logMessages") or []
    ins = [l for l in logs if "Instruction:" in l][:6]
    progs = sorted({ix.get("programId") for ix in r["transaction"]["message"]["instructions"]})
    pc = parse_create(r, dev)
    print(f"\n{mint[:10]} fábrica {dev[:8]} | firmantes {[s[:8] for s in signers]} | fábrica firma: {dev in signers}")
    print("   instrucciones:", ins); print("   programas:", [p[:8] for p in progs]); print("   parse_create:", pc)
    print("   creadores vistos que coinciden con algún firmante:", [s[:8] for s in signers if s in cr])
PY
