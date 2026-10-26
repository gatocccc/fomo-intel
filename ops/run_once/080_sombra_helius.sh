#!/bin/bash
# Sombra v2: creaciones leídas directo de la cadena (Helius, ~87/min vs 33/min de PumpPortal), 10 h. Sin plata.
cd /root/fomo_intel; set -a; . ./.env; set +a
nohup timeout 37000 python3 -u -m fomo_intel.experiments.tweet_shadow 36000 helius > state/ops/080_detalle.txt 2>&1 &
sleep 90
python3 - <<'PY'
import json
rows=[json.loads(l) for l in open("state/tweetshadow/creates_helius.jsonl")]
n=len(rows); print(f"90 s: {n} creados ({n/1.5:.0f}/min) | con tweet {sum(r['is_tweet'] for r in rows)} | metadatos ok {sum(1 for r in rows if not r['meta_src'].startswith('fail'))}/{n}")
print("mints sin 'pump':", sum(1 for r in rows if not r['mint'].endswith('pump')))
for r in rows[:6]: print(r["symbol"], r["mint"][-6:], r["meta_src"], r["twitter"][:70])
PY
tail -2 state/ops/080_detalle.txt
