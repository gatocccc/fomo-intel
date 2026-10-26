#!/bin/bash
# Dataset completo de tokens de tweet del día (texto del tweet, flujo seg 1-2, resultado simulado). En segundo plano.
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "variables de entorno disponibles (solo nombres):"; grep -oE '^[A-Z_]+' .env | tr '\n' ' '; echo
python3 -c "import anthropic" 2>/dev/null && echo "sdk anthropic: sí" || echo "sdk anthropic: no"
nohup timeout 5400 python3 -u -m fomo_intel.experiments.tweet_dataset > state/ops/085_detalle.txt 2>&1 &
sleep 45; cat state/ops/085_detalle.txt
