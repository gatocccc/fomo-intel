#!/bin/bash
# 30/10 — Verificación por HTTPS de /lab/ e /api/ideas; admin debe pedir clave (401).
cd /root/fomo_intel || exit 1
R="--resolve app.nonconformistducks.com:443:127.0.0.1"
curl -s $R https://app.nonconformistducks.com/lab/ | grep -c "Pitch Lloyd an idea"
curl -s $R https://app.nonconformistducks.com/api/ideas | head -c 200; echo
curl -s $R -o /dev/null -w "GET admin ideas sin clave: %{http_code}\n" https://app.nonconformistducks.com/api/admin/ideas
curl -s $R -o /dev/null -w "POST admin ideas sin clave: %{http_code}\n" -X POST -d '{}' https://app.nonconformistducks.com/api/admin/ideas
curl -s $R -X POST -H "Content-Type: application/json" -d '{"title":"x"}' https://app.nonconformistducks.com/api/ideas; echo
tail -3 state/research/good_wallets.log
