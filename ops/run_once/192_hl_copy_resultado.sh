#!/bin/bash
# 30/10 — Resultado del backtest de copiar traders de perps (lanzado en ops 191). Espera a que termine.
cd /root/fomo_intel || exit 1
for i in $(seq 1 55); do [ -f state/research/hl_copy.json ] && [ state/research/hl_copy.json -nt ops/run_once/191_hl_copy_lanzar.sh ] && break; sleep 10; done
tail -c 6000 state/research/hl_copy.log
