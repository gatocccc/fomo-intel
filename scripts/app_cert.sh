#!/bin/bash
# Pide el certificado HTTPS de app.nonconformistducks.com cuando el DNS ya apunta al servidor (lo llama server_sync).
D=app.nonconformistducks.com
[ -d /etc/letsencrypt/live/$D ] && exit 0
IP=$(getent ahostsv4 $D | awk 'NR==1{print $1}')
[ "$IP" = "37.27.29.220" ] || exit 0
certbot --nginx -d $D --non-interactive --agree-tos --redirect >> /root/fomo_intel/logs/cert.log 2>&1 && systemctl reload nginx
