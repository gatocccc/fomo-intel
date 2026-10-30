#!/bin/bash
# 30/10 — investigación: auditoría de costos de ejecución sobre nuestras operaciones reales (costo vs vela 1m previa + detector de sándwich por bloque).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 1500 python3 -u -m fomo_intel.experiments.exec_cost 2>&1 | tail -80
