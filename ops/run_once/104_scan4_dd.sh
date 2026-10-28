#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 600 python3 -u -m fomo_intel.desk.scan4
TOP=$(cat state/desk/scan4_top.txt 2>/dev/null)
echo; echo "=== chequeo anti-rug de los 5 mejores: $TOP ==="
[ -n "$TOP" ] && timeout 900 python3 -u -m fomo_intel.desk.dd $TOP | grep -v "^detalle"
