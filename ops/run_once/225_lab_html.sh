#!/bin/bash
cd /root/fomo_intel || exit 1
grep -c "floor-sect" dashboard/autopilot/lab/index.html; ls -la /var/www/autopilot/lab/ 2>&1 | head; grep -c "floor-sect" /var/www/autopilot/lab/index.html
curl -s -m 15 https://app.nonconformistducks.com/lab/ | grep -c "floor-sect"
grep -n "autopilot" /etc/nginx/sites-enabled/* 2>/dev/null | head -5
