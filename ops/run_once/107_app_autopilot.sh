#!/bin/bash
# Instala la app del piloto automático: servicio fomo-app (API en 127.0.0.1:8770) + sitio app.nonconformistducks.com.
set -e
cd /root/fomo_intel
python3 -c "import eth_account" 2>/dev/null || python3 -m pip install -q --break-system-packages "eth-account>=0.11"
cat > /etc/systemd/system/fomo-app.service <<UNIT
[Unit]
Description=Nonco Autopilot - API de la landing y el panel
After=network.target
[Service]
WorkingDirectory=/root/fomo_intel
EnvironmentFile=/root/fomo_intel/.env
ExecStart=/usr/bin/python3 -m fomo_intel.app.server
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl enable -q fomo-app; systemctl restart fomo-app; sleep 2; systemctl is-active fomo-app
mkdir -p /var/www/autopilot/admin
cp dashboard/autopilot/index.html /var/www/autopilot/index.html
cp dashboard/autopilot/admin.html /var/www/autopilot/admin/index.html
cat > /etc/nginx/sites-available/autopilot <<'NG'
server {
    listen 80;
    server_name app.nonconformistducks.com;
    root /var/www/autopilot;
    index index.html;
    client_max_body_size 64k;
    location /admin/ {
        auth_basic "Autopilot admin";
        auth_basic_user_file /etc/nginx/.htpasswd_fomo;
        try_files $uri $uri/ /admin/index.html;
        add_header Cache-Control "no-store";
    }
    location /api/admin/ {
        auth_basic "Autopilot admin";
        auth_basic_user_file /etc/nginx/.htpasswd_fomo;
        proxy_pass http://127.0.0.1:8770;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8770;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 20s;
    }
    location / {
        try_files $uri /index.html;
        add_header Cache-Control "no-cache";
    }
}
NG
ln -sf /etc/nginx/sites-available/autopilot /etc/nginx/sites-enabled/autopilot
nginx -t && systemctl reload nginx
echo "--- prueba local"
curl -s -H "Host: app.nonconformistducks.com" http://127.0.0.1/api/publico | head -c 300; echo
curl -s -o /dev/null -w "admin sin clave: %{http_code}\n" -H "Host: app.nonconformistducks.com" http://127.0.0.1/api/admin/resumen
curl -s -H "Host: app.nonconformistducks.com" "http://127.0.0.1/api/semaforo?objetivo=1.5&dias=30" | head -c 300; echo
echo "--- DNS"; getent ahostsv4 app.nonconformistducks.com || echo "todavía no resuelve"
bash scripts/app_cert.sh; ls /etc/letsencrypt/live/ ; cat state/plan_wallets.json
