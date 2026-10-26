#!/bin/bash
# Experimentos "red detrás" (26/10): descubrir launchpads en ST y lanzar las descargas (bags 30 d, pump 36 h) en segundo plano.
# Salidas: state/ops/exp_bags.log, state/ops/exp_pump.log (se publican con el estado). Datos en data/exp_red/.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 120 python3 -u -m fomo_intel.experiments.red discover
nohup python3 -u -m fomo_intel.experiments.red pull bags --days 30 --max 2500 > state/ops/exp_bags.log 2>&1 &
sleep 2
nohup python3 -u -m fomo_intel.experiments.red pull pump --hours 36 --max 2000 --min-buys 40 > state/ops/exp_pump.log 2>&1 &
echo "lanzados en segundo plano: $(pgrep -f experiments.red | wc -l) procesos"
