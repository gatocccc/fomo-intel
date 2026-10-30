#!/bin/bash
# 30/10: el dd de ops 158 devolvió LIMPIO vacío (0 billeteras, sin creador) para GTA6 y REMUS: eso es falta de datos, no un veredicto.
# Diagnóstico: claves presentes y respuesta cruda de Solana Tracker / Helius para GTA6. También confirma que el motor tomó writeoff.
cd /root/fomo_intel
set -a; . ./.env 2>/dev/null; set +a
for k in SOLANATRACKER_API_KEY SOLANA_TRACKER_API_KEY ST_API_KEY HELIUS_API_KEY; do echo "$k: $([ -n "${!k}" ] && echo si || echo no)"; done
grep -n "getenv\|environ" fomo_intel/desk/dd.py | head -12
timeout 300 python3 -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 2>&1 | grep -iv "^$" | head -30
echo "--- motor lab"; systemctl is-active fomo-desk@lab; grep -c writeoff fomo_intel/desk/engine.py
