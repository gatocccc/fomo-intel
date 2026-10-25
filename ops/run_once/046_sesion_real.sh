#!/bin/bash
# Marca el inicio de la sesión real actual (fábricas, 25/10 14:59 ART) para que la pantalla en vivo muestre solo eso.
cd /root/fomo_intel
python3 -c "
import json; json.dump({'start': 1792951145, 'start_sol': 1.2689, 'mode': 'real', 'strategy': 'factory', 'nota': 'sniper de fábricas en real desde 25/10 14:59 ART'}, open('state/session.json','w'), indent=1)"
cp dashboard/live.html /var/www/fomo/index.html
python3 -m fomo_intel.dashboard /var/www/fomo/historico.html
systemctl restart fomo-control; sleep 2; systemctl is-active fomo-control
curl -s http://127.0.0.1:8765/api/live | head -c 600; echo
