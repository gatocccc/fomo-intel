#!/bin/bash
# Reglas calculables al crearse el token (sin decu): precisión vs sus compras y simulación sobre TODOS los que cumplen.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u -m fomo_intel.experiments.tweet_rule 2>&1 | grep -v "^  tweet de"
