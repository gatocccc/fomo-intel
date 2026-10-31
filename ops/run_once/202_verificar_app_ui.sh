#!/bin/bash
# Verifica que el nuevo /app/ (My stool rediseñado) esté publicado por nginx.
sleep 90
grep -c "Pull up a" /var/www/autopilot/app/index.html
ls -la /var/www/autopilot/app/classic/index.html /var/www/autopilot/manifest.webmanifest /var/www/autopilot/assets/vendor/qrcode.js
for u in /app/ /app/classic/ /manifest.webmanifest /assets/fonts/bowlby-one-latin-400-normal.woff2 /assets/vendor/qrcode.js; do
  printf "%s " "$u"; curl -s -o /dev/null -w "%{http_code} %{content_type}\n" -H "Host: app.nonconformistducks.com" https://127.0.0.1$u -k
done
