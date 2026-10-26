#!/bin/bash
# ¿Qué hace comprar a decu? Contexto previo a cada compra grande (creador, fondeador, compradores previos, redes, herramienta de lanzamiento).
# Corre en segundo plano (puede tardar >10 min): resultado en state/ops/075_detalle.txt y state/decu_triggers.json
cd /root/fomo_intel; set -a; . ./.env; set +a
nohup timeout 2400 python3 -u -m fomo_intel.experiments.decu_triggers 60 48 > state/ops/075_detalle.txt 2>&1 &
echo "lanzado en segundo plano (pid $!)"
