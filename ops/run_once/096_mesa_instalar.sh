#!/bin/bash
# Mesa autónoma (pedido de Gastón 27/10 11:56): instala el motor como servicio permanente, apaga el bot viejo (no toca más la billetera),
# deja la página nueva como portada. Todavía SIN órdenes: las decisiones llegan por desk/decisions/.
cd /root/fomo_intel; set -a; . ./.env; set +a
pgrep -af "experiments.tweet_sniper|experiments.tweet_shadow" && pkill -f "experiments.tweet_" ; true
systemctl stop fomo-live; systemctl disable fomo-live 2>/dev/null; echo "fomo-live: $(systemctl is-active fomo-live)"
mkdir -p state/desk
cat > /etc/systemd/system/fomo-desk.service <<UNIT
[Unit]
Description=FOMO mesa autonoma
After=network-online.target
[Service]
WorkingDirectory=/root/fomo_intel
ExecStart=/usr/bin/python3 -u -m fomo_intel.desk.engine
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl enable --now fomo-desk; sleep 25
systemctl is-active fomo-desk; journalctl -u fomo-desk --no-pager -n 8
cp dashboard/desk.html /var/www/fomo/index.html; cp dashboard/live.html /var/www/fomo/bot.html
ls -la /var/www/fomo/ | head; python3 -c "import json;d=json.load(open('/var/www/fomo/desk.json'));print({k:d[k] for k in ('start_usd','equity_usd','cash_sol','sol_usd','goal_usd')})"
