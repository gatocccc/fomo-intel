#!/bin/bash
# 31/10 10:05 — Perps Hyperliquid: estructuras de los vaults que ganan (momentum cruzado, corto de débiles,
# largo majors/corto alts, tendencia por moneda). Universo completo con deslistados, diseño < 2025-07-01, prueba después.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 400 python3 -m fomo_intel.experiments.xsec_bt pull
setsid nohup python3 -m fomo_intel.experiments.xsec_bt analyze > state/research/xsec.log 2>&1 9>&- < /dev/null &
sleep 60; tail -20 state/research/xsec.log
