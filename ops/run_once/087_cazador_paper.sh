#!/bin/bash
# Entrena el modelo del cazador de tweets y lo lanza en modo PAPEL (sin plata) en segundo plano.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 -c "import sklearn" 2>/dev/null || python3 -m pip install -q --break-system-packages scikit-learn
mkdir -p state/tweetsniper
timeout 300 python3 -u -m fomo_intel.experiments.tweet_train
pkill -f "experiments.tweet_sniper" ; sleep 1
nohup timeout 30000 python3 -u -m fomo_intel.experiments.tweet_sniper > state/ops/087_cazador.log 2>&1 &
sleep 120
tail -15 state/ops/087_cazador.log
cat state/tweetsniper_summary.json | head -30
tail -5 state/tweetsniper/decisions.jsonl 2>/dev/null | cut -c1-300
