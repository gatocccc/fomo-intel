#!/bin/bash
cd /root/fomo_intel
for u in /plans/ /api/plans; do curl -sk -o /tmp/o -w "$u %{http_code}\n" --resolve app.nonconformistducks.com:443:127.0.0.1 https://app.nonconformistducks.com$u; head -c 200 /tmp/o; echo; done
curl -sk -o /dev/null -w "admin wallets sin clave %{http_code}\n" --resolve app.nonconformistducks.com:443:127.0.0.1 https://app.nonconformistducks.com/api/admin/wallets
systemctl is-active fomo-app fomo-desk fomo-desk@agresivo fomo-desk@equilibrado fomo-desk@tradicional
