#!/bin/bash
# 30/10 — tras desplegar el A/B de ruta de memecoins (Jupiter vs Solana Tracker, 50/50): servicios vivos, sin errores nuevos,
# y una cotización real de Jupiter para un memecoin que operamos (sin enviar nada).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
sleep 90
for s in fomo-desk@lloyd fomo-desk@lab fomo-desk@agresivo fomo-desk@equilibrado fomo-desk@tradicional fomo-mirror fomo-brain fomo-radar; do printf "%-24s %s\n" "$s" "$(systemctl is-active $s 2>&1)"; done
tail -5 logs/sync.log
echo "== errores recientes =="
journalctl -u 'fomo-desk@*' -u fomo-mirror --no-pager --since "-5 min" | grep -iE "error|traceback|exception" | tail -10 | cut -c1-220
echo "== cotización de prueba (GTA6, 0,1 SOL) =="
python3 -c "
from fomo_intel.live import executor as ex
tx,q=ex.jup_swap_tx(ex.SOL_MINT,'4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz',int(0.1e9),10.0,'AXbTdJLRephZMSAMoiRwfbCBWXFYtfHeLmbPj9TZk69M',0.0005)
print('ok tx', len(tx), 'out', q.get('outAmount'), 'ruta', [r['swapInfo']['label'] for r in q['routePlan']], 'share', ex.JUP_MEME_SHARE)"
