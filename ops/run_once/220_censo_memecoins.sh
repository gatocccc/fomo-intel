#!/bin/bash
# 31/10 09:50 — Censo de vida de memecoins (pedido de Gastón: "análisis súper profundo antes de la canasta").
# (1) probe de la API (créditos, campos, largo de velas); (2) descarga en segundo plano de 3 estratos
# (A todos 8/h·7d, B >=40 compras 20/h·7d, C >=1000 compras 10/h·14d con 48 h de velas). Resultado: state/research/censo/.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
mkdir -p state/research/censo
echo "=== probe ==="
timeout 240 python3 -m fomo_intel.experiments.censo probe
echo "=== pull en segundo plano ==="
pgrep -f "experiments.censo pull" && { echo "ya corre"; exit 0; }
setsid nohup python3 -m fomo_intel.experiments.censo pull --ka 8 --kb 20 --kc 10 --threads 3 > state/research/censo/pull.out 2>&1 9>&- < /dev/null &
sleep 20; tail -5 state/research/censo/pull.out
echo OK
