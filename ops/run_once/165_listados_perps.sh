#!/bin/bash
# 30/10: cola del lab — "short new perp listings after day 1": backtest sobre todos los listados de Hyperliquid desde jun-2023.
cd /root/fomo_intel
timeout 540 python3 scripts/listing_drift.py 2>&1 | tail -20
