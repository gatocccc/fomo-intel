#!/bin/bash
# Página para cargar claves (detrás del basic auth de fomo.nonconformistducks.com) + proxy /app-api/ -> API de la app.
cd /root/fomo_intel
cp dashboard/autopilot/claves.html /var/www/fomo/claves.html
CONF=/etc/nginx/sites-enabled/fomo
if ! grep -q "location /app-api/" "$CONF"; then
python3 - "$CONF" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
block = """    location /app-api/ {
        proxy_pass http://127.0.0.1:8770/api/;
        proxy_set_header X-Real-IP $remote_addr;
    }

"""
s = s.replace("    location / {", block + "    location / {", 1)
open(p, "w").write(s)
PY
fi
nginx -t && systemctl reload nginx
systemctl restart fomo-app; sleep 2
curl -s http://127.0.0.1:8770/api/admin/claves; echo
cat state/turnkey_pub.json 2>/dev/null
