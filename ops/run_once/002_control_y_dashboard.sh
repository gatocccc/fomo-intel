#!/bin/bash
# Instala la API de control (botones del dashboard), la expone en nginx bajo /api/ con el mismo basic auth,
# y pasa la regeneración del dashboard a cada minuto (la hace server_sync.sh).
set -e
cd /root/fomo_intel
cat > /etc/systemd/system/fomo-control.service <<UNIT
[Unit]
Description=FOMO Intel - API de control del dashboard
After=network.target
[Service]
WorkingDirectory=/root/fomo_intel
EnvironmentFile=/root/fomo_intel/.env
ExecStart=/usr/bin/python3 -m fomo_intel.live.control_server
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl enable -q fomo-control; systemctl restart fomo-control; sleep 1; systemctl is-active fomo-control
# nginx: location /api/ dentro del server de fomo
CONF=/etc/nginx/sites-enabled/fomo
if ! grep -q "location /api/" "$CONF"; then
python3 - "$CONF" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
block = """    location /api/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_read_timeout 10s;
    }

"""
s = s.replace("    location / {", block + "    location / {", 1)
open(p, "w").write(s)
PY
fi
nginx -t && systemctl reload nginx
# cron: sacar la regeneración cada 3 h (ahora la hace server_sync cada minuto)
( crontab -l | grep -v "fomo_intel.dashboard" ) | crontab -
python3 -m fomo_intel.dashboard /var/www/fomo/index.html
crontab -l
curl -s -X GET http://127.0.0.1:8765/api/status | head -c 300; echo
echo OK
