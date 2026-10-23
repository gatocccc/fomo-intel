#!/bin/bash
# Diagnóstico de la Swap API de Solana Tracker: distintas variantes de parámetros contra un token líquido y uno recién lanzado.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os, requests, time
pub = json.load(open("state/wallet_pub.json"))["pubkey"]
SOL = "So11111111111111111111111111111111111111112"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}
# token pump reciente: el último candidato/señal registrado
try:
    sig = [json.loads(l) for l in open("state/signals.jsonl") if l.strip()]
    fresh = [s for s in sig if s.get("move", 0) >= 3][-1]["mint"]
except Exception: fresh = BONK
for label, mint in (("BONK", BONK), ("reciente", fresh)):
    for variant in (
        {"from": SOL, "to": mint, "fromAmount": 0.05, "slippage": 10, "payer": pub, "priorityFee": 0.0005, "txVersion": "v0"},
        {"from": SOL, "to": mint, "fromAmount": 0.05, "slippage": 10, "payer": pub, "priorityFee": 0.0005},
        {"from": SOL, "to": mint, "fromAmount": "0.05", "slippage": "10", "payer": pub},
    ):
        for hh in (h, {}):
            t0 = time.time()
            try:
                r = requests.get("https://swap-v2.solanatracker.io/swap", params=variant, headers=hh, timeout=20)
                body = r.text
                try:
                    j = r.json(); keys = sorted(j.keys()); rate = j.get("rate"); body = json.dumps({"keys": keys, "rate": rate, "type": j.get("type"), "txVersion": j.get("txVersion")})[:600]
                except Exception: body = body[:300]
                print(f"{label} key={'si' if hh else 'no'} params={sorted(variant)} -> {r.status_code} {time.time()-t0:.1f}s {body}")
            except Exception as e:
                print(label, "error", e)
PY
