#!/bin/bash
# 31/10 18:00 — fondeadores de los creadores de tokens con nombre de marca (fábrica TESLA SI / SpaceX AI / Grok...).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
setsid nohup python3 -m fomo_intel.experiments.brand_factory > state/research/brand_factory.log 2>&1 9>&- < /dev/null &
sleep 30; tail -3 state/research/brand_factory.log
