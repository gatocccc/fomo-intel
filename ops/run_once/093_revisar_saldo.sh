#!/bin/bash
# ¿Por qué el saldo bajó de 1,3036 a 1,2454 SOL? Últimas transacciones de la billetera + estado del cazador real.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 200 python3 - <<'PY'
import json, os, requests, time
RPC=f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
pub=json.load(open("state/wallet_pub.json"))["pubkey"]
def rpc(m,p): return requests.post(RPC,json={"jsonrpc":"2.0","id":1,"method":m,"params":p},timeout=30).json().get("result")
sigs=rpc("getSignaturesForAddress",[pub,{"limit":25}]) or []
for s in sigs:
    tx=rpc("getTransaction",[s["signature"],{"encoding":"jsonParsed","maxSupportedTransactionVersion":1}]) or {}
    meta=tx.get("meta") or {}; keys=[k["pubkey"] for k in tx.get("transaction",{}).get("message",{}).get("accountKeys",[])]
    i=keys.index(pub) if pub in keys else 0
    d=(meta.get("postBalances",[0])[i]-meta.get("preBalances",[0])[i])/1e9 if meta else 0
    print(time.strftime("%H:%M:%S",time.gmtime(s["blockTime"]-3*3600)), f"{d:+.5f} SOL", "ERR" if s.get("err") else "ok", s["signature"][:12])
print("saldo:", rpc("getBalance",[pub])["value"]/1e9)
PY
echo "--- cazador"; grep -E "ENTRA|SALE|falló|Error|Traceback" state/ops/092_cazador_real.log | tail -10
cat state/tweetsniper/trades.jsonl 2>/dev/null | tail -6 | cut -c1-260
python3 -c "import json;s=json.load(open('state/tweetsniper_summary.json'));print('cerradas',s['closed'],'pnl',s['pnl_usd'],'abiertas',len(s['open']),s['stats'])"
