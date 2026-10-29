#!/bin/bash
# Cliente de Jupiter Perps: espec, posiciones, cotización y apertura EN SECO (no firma ni manda nada).
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 120 python3 -m scripts.perps_probe spec 2>&1 | head -150
echo "=== positions"; timeout 60 python3 -m scripts.perps_probe positions 2>&1 | head -20
echo "=== quote SOL short 10 USDC 2x"; timeout 60 python3 -m scripts.perps_probe quote SOL short 10 2 2>&1 | head -30
echo "=== open SOL short 10 2 --dry (legacy → instant)"; timeout 120 python3 -m scripts.perps_probe open SOL short 10 2 --dry 2>&1 | head -60
