#!/bin/bash
# 30/10 — ¿Ir en CONTRA de los traders top de Hyperliquid da ventaja? (pregunta de Gastón tras ops 191–192). Segundo plano, ~45 min.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
mkdir -p state/research
setsid nohup timeout 3500 python3 -m fomo_intel.experiments.hl_fade > state/research/hl_fade.log 2>&1 < /dev/null &
sleep 120
cut -c1-300 state/research/hl_fade.log
