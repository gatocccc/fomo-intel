#!/bin/bash
# Cerebro continuo (fomo-brain) en modo sombra + backtest de perps de Hyperliquid en segundo plano.
cd /root/fomo_intel; set -a; . ./.env; set +a
echo '{"modes": {"mesa": "shadow", "agresivo": "shadow", "equilibrado": "shadow", "tradicional": "shadow"}}' > state/brain_config.json
cat > /etc/systemd/system/fomo-brain.service <<UNIT
[Unit]
Description=FOMO desk brain (decide cada 10 min con reglas fijas; el motor ejecuta)
After=network.target
[Service]
WorkingDirectory=/root/fomo_intel
EnvironmentFile=/root/fomo_intel/.env
ExecStart=/usr/bin/python3 -m fomo_intel.desk.brain
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl enable -q --now fomo-brain; sleep 3
echo "fomo-brain: $(systemctl is-active fomo-brain)"
echo "--- Hyperliquid alcanzable"
curl -s -m 15 -X POST https://api.hyperliquid.xyz/info -H 'content-type: application/json' -d '{"type":"allMids"}' | python3 -c "import json,sys;d=json.load(sys.stdin);print({k:d.get(k) for k in ('SOL','BTC','ETH','JUP','kPEPE','WIF','FARTCOIN')})"
echo "--- precios Jupiter de los activos del plan tradicional"
curl -s -H "x-api-key: $JUPITER_API_KEY" "https://api.jup.ag/price/v3?ids=So11111111111111111111111111111111111111112,cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij,7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs,JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN" | python3 -c "import json,sys;d=json.load(sys.stdin);[print(k[:6],v.get('usdPrice'),v.get('liquidity')) for k,v in d.items()]"
echo "--- backtest de perps en segundo plano (log: state/ops/perps_bt.log)"
nohup python3 -u -m fomo_intel.experiments.perps_bt all > state/ops/perps_bt.log 2>&1 9>&- &
sleep 60; journalctl -u fomo-brain --no-pager -n 15
