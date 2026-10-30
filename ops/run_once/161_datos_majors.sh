#!/bin/bash
# 30/10 (sesión en vivo con Gastón): datos históricos para el backtest de majors (cripto diario/4h/1h desde 2020, funding HL, acciones).
cd /root/fomo_intel
timeout 500 python3 scripts/pull_majors.py 2>&1
