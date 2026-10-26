#!/bin/bash
# pump.fun, 7 días, >=40 compras: historia del creador para todos; velas solo para creadores con >=1 graduado previo (+8% control al azar).
cd /root/fomo_intel; set -a; . ./.env; set +a
nohup bash -c 'python3 -u -m fomo_intel.experiments.red pull pump pump7 --days 7 --max 9000 --min-buys 40 --only-good 1 && python3 -u -m fomo_intel.experiments.red analyze pump pump7' > state/ops/exp_pump7.log 2>&1 9>&- &
echo lanzado
