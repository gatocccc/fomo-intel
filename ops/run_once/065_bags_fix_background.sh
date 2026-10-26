#!/bin/bash
# Continúa fix_creators (resumible, con caché) sin límite de tiempo y luego analiza. Log: state/ops/exp_fix.log
cd /root/fomo_intel; set -a; . ./.env; set +a
nohup bash -c 'python3 -u -m fomo_intel.experiments.red fix_creators bags && python3 -u -m fomo_intel.experiments.red analyze bags && python3 -u -m fomo_intel.experiments.red analyze pump' > state/ops/exp_fix.log 2>&1 9>&- &
echo lanzado
