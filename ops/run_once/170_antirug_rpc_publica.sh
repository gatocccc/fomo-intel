#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "=== anti-rug con RPC pública (Helius en tope de uso) ==="
time timeout 540 python3 -u -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 7GWBnuU5ps1ZduiAsuKaYCehspfWWKZw69NF2E1xrZAA | grep -v "^detalle"
