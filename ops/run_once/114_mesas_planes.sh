#!/bin/bash
# Una mesa por plan del piloto automático (fomo-desk@agresivo, @equilibrado, @tradicional). Arrancan solas cuando la billetera recibe fondos.
cd /root/fomo_intel
cat > /etc/systemd/system/fomo-desk@.service <<UNIT
[Unit]
Description=Nonco Autopilot - mesa del plan %i
After=network.target
[Service]
WorkingDirectory=/root/fomo_intel
EnvironmentFile=/root/fomo_intel/.env
Environment=DESK_NAME=%i
ExecStart=/usr/bin/python3 -m fomo_intel.desk.engine
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
mkdir -p /var/www/autopilot/plans
systemctl daemon-reload
for p in agresivo equilibrado tradicional; do systemctl enable -q --now fomo-desk@$p; done
sleep 20
for p in agresivo equilibrado tradicional; do echo "== $p: $(systemctl is-active fomo-desk@$p)"; journalctl -u fomo-desk@$p --no-pager -n 4; cat state/plan_${p}_summary.json 2>/dev/null; echo; done
echo "--- precio por Jupiter"
set -a; . ./.env; set +a
curl -s -H "x-api-key: $JUPITER_API_KEY" "https://api.jup.ag/price/v3?ids=So11111111111111111111111111111111111111112" | head -c 300; echo
systemctl restart fomo-desk; sleep 5; systemctl is-active fomo-desk
