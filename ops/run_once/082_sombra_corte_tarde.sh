#!/bin/bash
# Corte de la tarde: sombra Helius vs compras de decu + simulación de entrar al seg 2 y 5 (velas 1 s de Solana Tracker).
cd /root/fomo_intel; set -a; . ./.env; set +a
tail -2 state/ops/081_detalle.txt
timeout 560 python3 -u -m fomo_intel.experiments.tweet_sim
