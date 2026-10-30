#!/bin/bash
# 30/10 — ¿Copiar a traders rentables de perps (Phantom/FOMO → Hyperliquid) da ventaja? Backtest fuera de muestra
# (elegir con días −60…−30, medir en −30…0, demora real en los últimos 3 días). Corre en segundo plano (~40 min).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
mkdir -p state/research
setsid nohup timeout 3300 python3 -m fomo_intel.experiments.hl_copy > state/research/hl_copy.log 2>&1 < /dev/null &
sleep 240
cat state/research/hl_copy.log | cut -c1-400
