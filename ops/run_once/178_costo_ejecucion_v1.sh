#!/bin/bash
# 30/10 — re-corrida de la auditoría 176 con maxSupportedTransactionVersion=1 (Solana ya tiene transacciones v1; getBlock fallaba).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 1500 python3 -u -m fomo_intel.experiments.exec_cost 2>&1 | tail -80
