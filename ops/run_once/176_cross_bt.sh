#!/bin/bash
# 30/10 ~19:30 UTC (sesión en vivo con Gastón): ¿los mercados de afuera (Nasdaq, S&P, oro, plata, dólar) anticipan a cripto en
# ventanas de horas? Backtest cruzado con datos de Yahoo (1 h, 730 d) y Binance (1 h). Resultado en state/research/cross_asset.json.
cd /root/fomo_intel
mkdir -p state/research
timeout 560 python3 -m fomo_intel.experiments.cross_bt state/research/cross_asset.json 2>&1
