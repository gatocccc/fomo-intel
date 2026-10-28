#!/bin/bash
# Guarda los identificadores de Turnkey (no son secretos) y prueba la clave con whoami.
cd /root/fomo_intel
for kv in "TURNKEY_ORG_ID=b33a7bb4-4cbf-43e9-90fd-044ef371b54c" "TURNKEY_API_USER_ID=a7d755dc-8f80-4b81-bd22-554350dbff7e"; do
  k=${kv%%=*}; grep -v "^$k=" .env > .env.tmp; echo "$kv" >> .env.tmp; mv .env.tmp .env
done
chmod 600 .env
set -a; . ./.env; set +a
python3 -m fomo_intel.app.turnkey
