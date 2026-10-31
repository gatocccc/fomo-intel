#!/bin/bash
# Verifica el Live book nuevo, ui.css/ui.js/fonts.css publicados (corre en la pasada siguiente al rsync).
for u in /book/ /book/classic/ /app/ /ui.css /ui.js /fonts.css /lab/ /; do
  printf "%s " "$u"; curl -s -o /tmp/p -w "%{http_code} %{content_type} " -H "Host: app.nonconformistducks.com" https://127.0.0.1$u -k; wc -c </tmp/p
done
grep -c "UI.draw" /var/www/autopilot/book/index.html
