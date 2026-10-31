#!/bin/bash
# 30/10 — Idea de Gastón: ¿si entran k billeteras "buenas" (medidas en la 1.ª mitad del mes) al mismo token, es oportunidad?
# Corre en segundo plano (~30–50 min). Resultado: state/research/good_wallets.json
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
mkdir -p state/research
setsid nohup timeout 3300 python3 -m fomo_intel.experiments.good_wallets > state/research/good_wallets.log 2>&1 < /dev/null 9>&- &
sleep 120
cut -c1-300 state/research/good_wallets.log
