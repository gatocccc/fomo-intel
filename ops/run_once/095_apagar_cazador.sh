#!/bin/bash
# Pedido de Gastón 22:57: apagar el cazador de tweets. Primero desactiva entradas, espera que cierren las abiertas (máx 3 min), después mata el proceso.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json; p="state/tweetsniper/control.json"; c=json.load(open(p)); c["enabled"]=False; json.dump(c,open(p,"w"),indent=1); print("enabled=False")
PY
for i in $(seq 1 36); do
  n=$(python3 -c "import json;print(len(json.load(open('state/tweetsniper_summary.json'))['open']))"); [ "$n" = "0" ] && break; sleep 5
done
echo "abiertas: $n"
pkill -f "experiments.tweet_sniper"; sleep 2; pgrep -af tweet_sniper || echo "cazador apagado"
python3 - <<'PY'
import json
rows=[json.loads(l) for l in open("state/tweetsniper/closed.jsonl")]
print(f"real: {len(rows)} cerradas | ganadas {sum((r['ret'] or 0)>0 for r in rows)} | pnl US$ {sum(r['pnl_usd'] for r in rows):+.2f}")
for r in rows: print("  ",r["symbol"],r["why"],r["ret"],r["pnl_usd"],"pico",r["peak_mult"],"hold",r["hold_s"],"edad entrada",r["entry_age_s"])
tr=[json.loads(l) for l in open("state/tweetsniper/trades.jsonl")]
print("compras ok:",sum(1 for t in tr if t["side"]=="buy" and t["ok"]),"| compras fallidas:",sum(1 for t in tr if t["side"]=="buy" and not t["ok"]),"| latencia compra media:",round(sum(t.get("lat",0) for t in tr if t["side"]=="buy" and t["ok"])/max(1,sum(1 for t in tr if t["side"]=="buy" and t["ok"])),1))
PY
python3 -c "
import json; from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
print('saldo:', Rpc(Env().rpc_url).sol_balance(json.load(open('state/wallet_pub.json'))['pubkey']))"
