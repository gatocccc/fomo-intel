#!/bin/bash
# Diagnóstico: Helius no detecta operaciones de decu (todo "skipped").
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 150 python3 -u -m fomo_intel.experiments.diag_decu 9>&-
