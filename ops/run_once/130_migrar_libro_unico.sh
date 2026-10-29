#!/bin/bash
# Migración a un solo libro ("lloyd"): junta las tres billeteras de los planes en una, arranca su motor y apaga los tres planes.
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "--- paro los motores de los planes y el cerebro (nadie opera mientras se mueve la plata)"
systemctl stop fomo-brain fomo-desk@agresivo fomo-desk@equilibrado fomo-desk@tradicional
sleep 3
echo "--- ensayo"
timeout 300 python3 -u -m fomo_intel.desk.migrate_book --dry
echo "--- migración real"
timeout 900 python3 -u -m fomo_intel.desk.migrate_book
echo "--- servicios"
systemctl disable -q fomo-desk@agresivo fomo-desk@equilibrado fomo-desk@tradicional
systemctl enable -q --now fomo-desk@lloyd
echo '{"modes": {"mesa": "live", "lloyd": "live", "agresivo": "off", "equilibrado": "off", "tradicional": "off"}}' > state/brain_config.json
systemctl start fomo-brain
sleep 45
echo "fomo-desk@lloyd: $(systemctl is-active fomo-desk@lloyd) · fomo-brain: $(systemctl is-active fomo-brain) · fomo-app: $(systemctl is-active fomo-app)"
journalctl -u fomo-desk@lloyd --no-pager -n 8
python3 -c "
import json;d=json.load(open('state/plan_lloyd_summary.json'));print('libro',d.get('equity_usd'),'start',d.get('start_usd'),'cash',d.get('cash_sol'));[print(' ',p['symbol'],p.get('sleeve'),p['mult'],p['value_usd']) for p in d.get('positions',[])]"
echo "--- saldos que quedaron en las billeteras viejas"
for p in equilibrado tradicional; do W=$(python3 -c "import json;print(json.load(open('secrets/plan_$p.json'))['pubkey'])"); echo -n "$p $W SOL="; curl -s $SOLANA_RPC_URL -X POST -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getBalance","params":["'$W'"]}' | python3 -c "import json,sys;print(json.load(sys.stdin)['result']['value']/1e9)"; done
echo "--- API"
sleep 5; curl -s --resolve app.nonconformistducks.com:443:127.0.0.1 https://app.nonconformistducks.com/api/book -k | head -c 700; echo
curl -s --resolve app.nonconformistducks.com:443:127.0.0.1 "https://app.nonconformistducks.com/api/expect?risk=35" -k | head -c 400; echo
for u in / /book/ /app/ /admin/ /plans/; do curl -sk -o /dev/null -w "$u %{http_code}\n" --resolve app.nonconformistducks.com:443:127.0.0.1 https://app.nonconformistducks.com$u; done
