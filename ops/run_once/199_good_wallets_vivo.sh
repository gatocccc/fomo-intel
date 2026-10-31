#!/bin/bash
# 30/10 — Verifica que fomo-radar escucha las 14 billeteras buenas (prueba en vivo del lab, k=3).
cd /root/fomo_intel || exit 1
sleep 90
systemctl is-active fomo-radar
journalctl -u fomo-radar --since "-3 min" --no-pager | grep -i "kols\|good" | tail -6
python3 -c "import json;d=json.load(open('state/desk/good_wallets.json'));print({k:d.get(k) for k in ('mode','k','wallets','connected','notifications','buys_seen','errors','verdict')});print('hot',d.get('hot')[:3])"
python3 -c "import json;d=json.load(open('state/desk/kols.json'));print('kols sigue:',{k:d.get(k) for k in ('connected','wallets','buys_seen')})"
