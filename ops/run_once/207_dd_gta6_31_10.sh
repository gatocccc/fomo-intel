#!/bin/bash
# 31/10 03:39: anti-rug de la posición abierta GTA6 (mesa) antes de decidir.
cd /root/fomo_intel
set -a; . ./.env 2>/dev/null; set +a
timeout 300 python3 -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 2>&1 | grep -v "^$" | head -30
