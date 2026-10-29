#!/bin/bash
# Checklist antes de la prueba con 5 holders.
cd /root/fomo_intel
set -a; . ./.env; set +a
echo "contratos: ${NONCO_CONTRACTS:-(vacío)}"
for c in $(echo "$NONCO_CONTRACTS" | tr ',' ' '); do
  # name() del contrato y totalSupply para confirmar que son NFTs reales
  n=$(curl -s -m 10 https://ethereum-rpc.publicnode.com -H 'content-type: application/json' -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"$c\",\"data\":\"0x06fdde03\"},\"latest\"]}" | python3 -c "import json,sys;r=json.load(sys.stdin).get('result','0x');b=bytes.fromhex(r[2:]);print(b[64:64+int.from_bytes(b[32:64],'big')].decode(errors='replace') if len(b)>64 else 'sin nombre')")
  s=$(curl -s -m 10 https://ethereum-rpc.publicnode.com -H 'content-type: application/json' -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"$c\",\"data\":\"0x18160ddd\"},\"latest\"]}" | python3 -c "import json,sys;print(int(json.load(sys.stdin).get('result','0x0'),16))")
  echo "  $c -> $n, supply $s"
done
echo "servicios:"; systemctl is-active fomo-app fomo-mirror fomo-desk@lloyd fomo-brain | paste -sd' '
echo "api:"; curl -s -o /dev/null -w "%{http_code} " https://app.nonconformistducks.com/api/book; curl -s -o /dev/null -w "%{http_code} " https://app.nonconformistducks.com/api/config; curl -s -o /dev/null -w "%{http_code}\n" https://app.nonconformistducks.com/app/
echo "holders pendientes re-chequeo:"; python3 - <<'PY'
import sqlite3
c=sqlite3.connect('state/app/app.db'); c.row_factory=sqlite3.Row
rows=c.execute("select id,email,holder_status,ducks,status,bot_wallet from users").fetchall()
print(len(rows),'cuentas'); [print(' ',dict(r)) for r in rows[:20]]
PY
curl -s 127.0.0.1:8770/api/admin/resumen | python3 -c "import json,sys;d=json.load(sys.stdin);print('holders',d['holders'],'pending',d['holders_pending'],'contratos API',d['holder_contracts'])"
echo "house:"; cat state/users/_all.json | head -5
echo "sync:"; tail -3 logs/sync.log; tail -3 logs/sync.err 2>/dev/null
