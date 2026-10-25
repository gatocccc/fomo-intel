#!/bin/bash
cd /root/fomo_intel; echo "$(date -u) STOP: backtest de fabricas invalidado (la apertura de la vela es previa a la compra de la fabrica)" > state/STOP; cat state/STOP
