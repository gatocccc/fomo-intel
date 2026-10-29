#!/bin/bash
cd /root/fomo_intel
sleep 15
systemctl is-active fomo-app
curl -s 127.0.0.1:8770/api/config | python3 -c "import json,sys;print(json.load(sys.stdin)['fees'])"
grep -c "15%" /var/www/autopilot/index.html
grep -c 'min="300"' /var/www/autopilot/app/index.html
