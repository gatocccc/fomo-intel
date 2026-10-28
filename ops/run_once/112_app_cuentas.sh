#!/bin/bash
# Cuentas con email y contraseña, sitio en inglés: copia la web completa, ajusta nginx y reinicia la API.
cd /root/fomo_intel
which rsync >/dev/null || apt-get install -y -q rsync >/dev/null
rsync -a --exclude claves.html dashboard/autopilot/ /var/www/autopilot/
cp dashboard/autopilot/claves.html /var/www/fomo/claves.html
F=/etc/nginx/sites-available/autopilot
sed -i 's#try_files $uri /index.html;#try_files $uri $uri/ /index.html;#' $F
grep -q "location /app/" $F || sed -i 's#    location / {#    location /app/ {\n        try_files $uri $uri/ /app/index.html;\n        add_header Cache-Control "no-cache";\n    }\n    location / {#' $F
nginx -t && systemctl reload nginx
systemctl restart fomo-app; sleep 2; systemctl is-active fomo-app
curl -s -H "Host: app.nonconformistducks.com" http://127.0.0.1/api/config; echo
curl -s -o /dev/null -w "app page %{http_code}\n" -H "Host: app.nonconformistducks.com" http://127.0.0.1/app/
ls /etc/letsencrypt/live/; tail -5 logs/cert.log 2>/dev/null
getent ahostsv4 app.nonconformistducks.com | head -1
