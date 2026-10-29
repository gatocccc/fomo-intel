#!/bin/bash
# Motor de seguidores (fomo-mirror): una billetera por usuario con asiento, sigue al libro de Lloyd. Decisión de Gastón 29/10.
cd /root/fomo_intel
mkdir -p secrets/users state/users
cat > /etc/systemd/system/fomo-mirror.service <<UNIT
[Unit]
Description=Lloyd's Tavern - stools (user wallets following the book)
After=network.target
[Service]
WorkingDirectory=/root/fomo_intel
EnvironmentFile=/root/fomo_intel/.env
ExecStart=/usr/bin/python3 -m fomo_intel.desk.mirror
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q --now fomo-mirror
systemctl restart fomo-app
sleep 25
systemctl is-active fomo-mirror fomo-app
journalctl -u fomo-mirror --no-pager -n 12
ls -la secrets/house_fees.json state/users/ 2>/dev/null
curl -s 127.0.0.1:8770/api/admin/resumen | python3 -c "import json,sys;d=json.load(sys.stdin);print('users',d['users'],'fees',d.get('fees_usd'),'house',d.get('house_fee_wallet'))"
