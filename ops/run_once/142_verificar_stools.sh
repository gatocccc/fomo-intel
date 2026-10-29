#!/bin/bash
cd /root/fomo_intel
sleep 10
systemctl is-active fomo-mirror fomo-app
journalctl -u fomo-mirror --no-pager -n 5
grep -c "Buy Lloyd's lab a round" /var/www/autopilot/app/index.html
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Content-Type: application/json" -d '{"sol":0.1}' 127.0.0.1:8770/api/me/tip
cat state/users/_all.json
