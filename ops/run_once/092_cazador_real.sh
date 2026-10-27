#!/bin/bash
# Pedido de Gastón 26/10 21:46: "abrilo ahora con plata real y corta si pierde 30".
# Cazador de tweets en REAL: US$5 por operación, máx 3 abiertas, corte -US$30 total (y -US$30 en el día). Umbral 0,27.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json
rows=[json.loads(l) for l in open("state/tweetsniper/closed.jsonl")] if __import__("os").path.exists("state/tweetsniper/closed.jsonl") else []
v=[r["ret"] for r in rows if r.get("ret") is not None]
print(f"papel hasta ahora: {len(rows)} cerradas | ganadas {sum(x>0 for x in v)} | ret medio {sum(v)/max(len(v),1):+.3f} | pnl US$ {sum(r['pnl_usd'] for r in rows):+.2f}")
for r in rows[-12:]: print("  ", r["symbol"], r["why"], r["ret"], r["peak_mult"], r["score"])
PY
SALDO=$(python3 -c "
import json; from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
print(Rpc(Env().rpc_url).sol_balance(json.load(open('state/wallet_pub.json'))['pubkey']))")
echo "saldo billetera: $SALDO SOL"
pkill -f "experiments.tweet_sniper"; sleep 2
stamp=$(date +%Y%m%d_%H%M); mkdir -p state/tweetsniper/papel
for f in closed.jsonl trades.jsonl decisions.jsonl; do [ -f state/tweetsniper/$f ] && mv state/tweetsniper/$f state/tweetsniper/papel/${stamp}_$f; done
python3 - "$SALDO" <<'PY'
import json, sys, time
p="state/tweetsniper/control.json"; c=json.load(open(p))
c.update({"enabled": True, "mode": "real", "size_usd": 5.0, "max_open": 3, "total_loss_usd": 30.0, "daily_loss_usd": 30.0, "threshold": 0.27})
json.dump(c, open(p,"w"), indent=1); print("control:", c)
json.dump({"start": time.time(), "start_sol": float(sys.argv[1]), "nota": "cazador de tweets en real, corte -US$30"}, open("state/tweetsniper/session.json","w"))
PY
nohup timeout 86000 python3 -u -m fomo_intel.experiments.tweet_sniper > state/ops/092_cazador_real.log 2>&1 &
sleep 90
grep -E "conectado|ENTRA|SALE|Traceback|Error" state/ops/092_cazador_real.log | tail -8
python3 -c "import json;s=json.load(open('state/tweetsniper_summary.json'));print('modo',s['ctrl']['mode'],'| lag',s['lag_slots'],'| stats',s['stats'])"
