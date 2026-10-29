#!/bin/bash
# ¿Se puede estacionar el efectivo en jlUSDC (Jupiter Lend Earn) con un swap común? Solo cotiza, no compra.
cd /root/fomo_intel; set -a; . ./.env; set +a
for u in "https://api.jup.ag/lend/v1/earn/tokens" "https://lite-api.jup.ag/lend/v1/earn/tokens"; do
  echo "--- $u"; curl -s -m 20 -H "x-api-key: $JUPITER_API_KEY" "$u" | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print('no json',e); sys.exit()
rows=d if isinstance(d,list) else d.get('tokens') or d.get('data') or []
print('filas',len(rows))
for r in rows:
    s=json.dumps(r)
    if 'USDC' in s.upper(): print({k:r.get(k) for k in list(r)[:14]})
" ; done
echo "--- cotización Jupiter SOL -> jlUSDC (0,5 SOL) y USDC -> jlUSDC"
curl -s -m 20 -H "x-api-key: $JUPITER_API_KEY" "https://api.jup.ag/swap/v1/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=9BEcn9aPEmhSPbPQeFGjidRiEKki46fVQDyPpSQXPA2D&amount=500000000&slippageBps=50" | head -c 600; echo
curl -s -m 20 -H "x-api-key: $JUPITER_API_KEY" "https://api.jup.ag/swap/v1/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint=9BEcn9aPEmhSPbPQeFGjidRiEKki46fVQDyPpSQXPA2D&amount=50000000&slippageBps=50" | head -c 600; echo
echo "--- cotización por la vía del bot (Solana Tracker) SOL -> jlUSDC"
python3 - <<'PY'
import os
from fomo_intel.live.executor import real_quote
try:
    q=real_quote("So11111111111111111111111111111111111111112","9BEcn9aPEmhSPbPQeFGjidRiEKki46fVQDyPpSQXPA2D",0.5,1,"EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4",0.001,os.environ.get("SOLANATRACKER_API_KEY",""))
    print("rate", q.get("rate"))
except Exception as e: print("error", e)
PY
curl -s -H "x-api-key: $JUPITER_API_KEY" "https://api.jup.ag/price/v3?ids=9BEcn9aPEmhSPbPQeFGjidRiEKki46fVQDyPpSQXPA2D" ; echo
