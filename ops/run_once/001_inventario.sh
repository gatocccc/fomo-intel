#!/bin/bash
# Inventario del servidor: qué hay instalado, dónde vive el dashboard, servicios y nginx.
cd /root/fomo_intel
echo "--- python"; python3 --version; python3 -m pip --version
echo "--- arbol (sin data)"; find . -path ./data -prune -o -path ./.git -prune -o -path ./__pycache__ -prune -o -type f -print | grep -v __pycache__ | sort
echo "--- servicios"; systemctl list-units --type=service --all --no-pager | grep -Ei 'fomo|dash|gunicorn|flask|nginx|caddy' 
echo "--- nginx"; ls /etc/nginx/sites-enabled/ 2>/dev/null; for f in /etc/nginx/sites-enabled/*; do echo "## $f"; cat "$f"; done 2>/dev/null
echo "--- crontab"; crontab -l
echo "--- puertos"; ss -ltnp 2>/dev/null | head -30
echo "--- .env (claves ocultas)"; sed -E 's/=(.{4}).*/=\1.../' .env
echo "--- estado"; ls -la state secrets; cat state/service.txt 2>/dev/null
echo "--- bot"; journalctl -u fomo-live --no-pager -n 40
echo "--- disco"; df -h / | tail -1; free -m | head -2
