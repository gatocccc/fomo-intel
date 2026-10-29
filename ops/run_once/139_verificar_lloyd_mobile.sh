#!/bin/bash
# Verifica el despliegue del historial desde el día uno y la versión mobile de Lloyd's Tavern.
cd /root/fomo_intel
sleep 20
systemctl is-active fomo-app
curl -s 127.0.0.1:8770/api/book | python3 -c "import json,sys;d=json.load(sys.stdin);t=d.get('track',{});print('track', {k:(v.get('pct'),v.get('since'),len(v.get('series',[]))) for k,v in t.items()});print('journal kinds', sorted({j['kind'] for j in d['journal']}))"
grep -c tabbar /var/www/autopilot/lloyd.js
grep -c "Since day one" /var/www/autopilot/index.html /var/www/autopilot/book/index.html
