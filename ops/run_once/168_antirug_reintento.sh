#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "=== perps abiertos (Jupiter) ==="
timeout 60 python3 -m scripts.perps_probe positions 2>&1 | head -20
echo "=== anti-rug GTA6 + top scan4 (con RPC robusta) ==="
timeout 900 python3 -u -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 7GWBnuU5ps1ZduiAsuKaYCehspfWWKZw69NF2E1xrZAA BZFYNPeQAEW3HWQ4DNsTVahC1n4ZjTgn6jB2nnBbB96W npz2FhoufQ7pKqhGpaipYWacrAkidyW2yDpVWSvpump | grep -v "^detalle"
