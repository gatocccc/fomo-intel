#!/bin/bash
# Cazador v3: metadatos en paralelo (varios gateways IPFS). Sigue en PAPEL.
cd /root/fomo_intel; set -a; . ./.env; set +a
pkill -f "experiments.tweet_sniper"; sleep 2
mv state/tweetsniper/decisions.jsonl state/tweetsniper/decisions_v2.jsonl 2>/dev/null
nohup timeout 30000 python3 -u -m fomo_intel.experiments.tweet_sniper > state/ops/089_cazador.log 2>&1 &
sleep 150
python3 - <<'PY'
import json
s=json.load(open("state/tweetsniper_summary.json")); print("atraso (slots):", s.get("lag_slots"), "| stats:", s["stats"], "| cerradas:", s["closed"], "pnl", s["pnl_usd"])
rows=[json.loads(l) for l in open("state/tweetsniper/decisions.jsonl")]
print("decisiones de tweet:", len(rows), "| ENTRA:", sum(1 for r in rows if r["decision"]=="ENTRA"))
for r in sorted(rows, key=lambda r:-r["score"])[:4]: print("  ", r["symbol"], r["score"], r["vol_s1"], r["px_s1"], r["rank"], r["author"], r["decision"])
PY
