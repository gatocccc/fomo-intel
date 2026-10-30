#!/bin/bash
# 30/10 — investigación (costos): A/B de ruta sólo con cotizaciones (sin plata): Jupiter vs Solana Tracker en los memecoins que operamos.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
mkdir -p state/research
timeout 900 python3 -u -m fomo_intel.experiments.route_ab 2>&1 | tail -60
