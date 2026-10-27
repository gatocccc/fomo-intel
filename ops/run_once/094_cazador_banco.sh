#!/bin/bash
# Cazador real + banco por nombre/tweet tras un stop (60 min). Reinicia SOLO sin posiciones abiertas (hasta 8 min esperando).
cd /root/fomo_intel; set -a; . ./.env; set +a
for i in $(seq 1 96); do
  n=$(python3 -c "import json;print(len(json.load(open('state/tweetsniper_summary.json'))['open']))")
  [ "$n" = "0" ] && break; sleep 5
done
echo "abiertas al reiniciar: $n"
[ "$n" = "0" ] || { echo "NO reinicio: hay posiciones abiertas"; exit 1; }
pkill -f "experiments.tweet_sniper"; sleep 2
nohup timeout 86000 python3 -u -m fomo_intel.experiments.tweet_sniper > state/ops/094_cazador_real.log 2>&1 &
sleep 30; grep -E "conectado|Traceback" state/ops/094_cazador_real.log | tail -3
