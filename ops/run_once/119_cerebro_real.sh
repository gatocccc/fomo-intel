#!/bin/bash
# Cerebro a real en las cuatro mesas (filtros de entrada endurecidos tras la corrida en sombra) + pares de memes con k=2.
cd /root/fomo_intel; set -a; . ./.env; set +a
sleep 20   # que el sync reinicie fomo-brain con el código nuevo
echo '{"modes": {"mesa": "live", "agresivo": "live", "equilibrado": "live", "tradicional": "live"}}' > state/brain_config.json
systemctl restart fomo-brain; sleep 5; echo "fomo-brain: $(systemctl is-active fomo-brain)"
nohup python3 -u -m fomo_intel.experiments.perps_bt analyze > state/ops/perps_bt2.log 2>&1 9>&- &
sleep 90; journalctl -u fomo-brain --no-pager -n 12; ls state/desk/auto state/plan_*/auto 2>/dev/null
