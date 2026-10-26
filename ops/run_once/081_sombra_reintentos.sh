#!/bin/bash
# Apaga la sombra vieja (PumpPortal) y relanza la de Helius con reintentos de metadatos (gateways IPFS alternativos).
cd /root/fomo_intel; set -a; . ./.env; set +a
pkill -f "experiments.tweet_shadow" ; sleep 2; pgrep -af tweet_shadow || echo "ninguna corriendo"
mv state/tweetshadow/creates_helius.jsonl state/tweetshadow/creates_helius_prueba.jsonl 2>/dev/null
nohup timeout 37000 python3 -u -m fomo_intel.experiments.tweet_shadow 36000 helius > state/ops/081_detalle.txt 2>&1 &
sleep 120
python3 - <<'PY'
import json
from collections import Counter
rows=[json.loads(l) for l in open("state/tweetshadow/creates_helius.jsonl")]
n=len(rows); ok=[r for r in rows if not r['meta_src'].startswith('fail')]
print(f"{n} creados en ~2 min | metadatos ok {len(ok)}/{n} | con tweet {sum(r['is_tweet'] for r in rows)}")
print("fallas:", Counter(r['meta_src'] for r in rows if r['meta_src'].startswith('fail')).most_common(4))
lat=sorted(r['meta_lat_s'] for r in ok); print("latencia mediana", lat[len(lat)//2] if lat else None)
PY
