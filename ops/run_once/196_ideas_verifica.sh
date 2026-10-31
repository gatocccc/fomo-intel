#!/bin/bash
# 30/10 — Verifica la sección de ideas de la comunidad (/lab/ → /api/ideas) tras el deploy.
cd /root/fomo_intel || exit 1
sleep 20
systemctl is-active fomo-app
H="Host: app.nonconformistducks.com"
curl -s -H "$H" http://127.0.0.1/api/ideas | head -c 300; echo
curl -s -o /dev/null -w "admin ideas sin clave: %{http_code}\n" -H "$H" http://127.0.0.1/api/admin/ideas
curl -s http://127.0.0.1:8770/api/admin/ideas | head -c 200; echo
grep -c "Pitch Lloyd an idea" /var/www/autopilot/lab/index.html
ls -l state/research/ideas_inbox.json 2>/dev/null || echo "inbox se crea con la primera idea"
echo "--- good_wallets"; tail -5 state/research/good_wallets.log
