#!/bin/bash
# Cazador v2: ventana por slots de cadena (no por reloj), apaga la sombra vieja (competía por IPFS y CPU).
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 -c "import orjson" 2>/dev/null || python3 -m pip install -q --break-system-packages orjson 2>&1 | tail -1
pkill -f "experiments.tweet_shadow"; pkill -f "experiments.tweet_sniper"; sleep 2
mv state/tweetsniper/decisions.jsonl state/tweetsniper/decisions_v1.jsonl 2>/dev/null
nohup timeout 30000 python3 -u -m fomo_intel.experiments.tweet_sniper > state/ops/088_cazador.log 2>&1 &
sleep 150
tail -6 state/ops/088_cazador.log
python3 - <<'PY'
import json
s=json.load(open("state/tweetsniper_summary.json")); print("atraso (slots):", s.get("lag_slots"), "| stats:", s["stats"], "| tokens:", s.get("tokens_tracked"))
rows=[json.loads(l) for l in open("state/tweetsniper/decisions.jsonl")]
v=sorted(r["vol_s1"] for r in rows); print("decisiones:", len(rows), "| vol_s1 p25/p50/p75:", v[len(v)//4] if v else None, v[len(v)//2] if v else None, v[3*len(v)//4] if v else None)
print("con vol_s1>0:", sum(1 for r in rows if r["vol_s1"]>0), "| score máx:", max((r["score"] for r in rows), default=None))
for r in sorted(rows, key=lambda r:-r["score"])[:5]: print("  ", r["symbol"], r["score"], r["vol_s1"], r["px_s1"], r["rank"], r["author"], r["decision"])
PY
