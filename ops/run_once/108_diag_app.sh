#!/bin/bash
cd /root/fomo_intel
ls -l /etc/nginx/sites-enabled/
nginx -T 2>/dev/null | grep -nE "listen|server_name|include" | head -60
echo "--- curl 127.0.0.1:8770"; curl -s http://127.0.0.1:8770/api/publico | head -c 200; echo
echo "--- curl ip publica"; curl -s -H "Host: app.nonconformistducks.com" http://37.27.29.220/api/publico | head -c 200; echo
journalctl -u fomo-app --no-pager -n 20
