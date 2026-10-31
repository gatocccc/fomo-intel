#!/bin/bash
# Verifica que el Lloyd nuevo esté publicado (md5 de assets servidos vs repo).
cd /root/fomo_intel
for f in lloyd.webp lloyd-head.png favicon.png og.jpg icon-512.png; do
  a=$(md5sum < dashboard/autopilot/assets/$f | cut -c1-8)
  b=$(curl -sk -H "Host: app.nonconformistducks.com" "https://127.0.0.1/assets/$f?v=2" | md5sum | cut -c1-8)
  echo "$f repo=$a served=$b"
done
grep -c "lloyd.webp?v=2" /var/www/autopilot/index.html
