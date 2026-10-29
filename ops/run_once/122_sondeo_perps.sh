#!/bin/bash
# Sondeo de la API de Jupiter Perps (la que usa su propia app). Solo cotiza y pide la transacción sin firmar; NO firma ni manda nada.
cd /root/fomo_intel; set -a; . ./.env; set +a
W=EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4
echo "--- posiciones actuales de la billetera del plan tradicional"
curl -s -m 20 "https://perps-api.jup.ag/v1/positions?walletAddress=$W" | head -c 600; echo
echo "--- market-stats SOL"
curl -s -m 20 "https://perps-api.jup.ag/v1/market-stats?mint=So11111111111111111111111111111111111111112" | head -c 500; echo
echo "--- increase: short SOL, 10 USDC de colateral, 2x, con transacción serializada"
curl -s -m 30 -X POST https://perps-api.jup.ag/v1/positions/increase -H 'content-type: application/json' -d '{"walletAddress":"'$W'","marketMint":"So11111111111111111111111111111111111111112","inputMint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","collateralMint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","side":"short","leverage":"2","maxSlippageBps":"100","collateralTokenDelta":"10000000","includeSerializedTx":true,"tpsl":[]}' | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print('no json',e); sys.exit()
q=d.get('quote') or {}
print('quote', {k:q.get(k) for k in ('entryPriceUsd','leverage','liquidationPriceUsd','openFeeUsd','priceImpactFeeUsd','positionSizeUsd','positionCollateralSizeUsd','collateralLessThanFees')})
print('tx?', bool(d.get('serializedTxBase64')), 'len', len(d.get('serializedTxBase64') or ''), 'keeper', d.get('requireKeeperSignature'), 'type', d.get('transactionType'), 'pos', d.get('positionPubkey'))
print('otros', {k:v for k,v in d.items() if k not in ('quote','serializedTxBase64','txMetadata')})
print('meta', d.get('txMetadata'))
if 'error' in d or 'message' in d: print('ERROR', d)
"
echo "--- increase: long BTC, 10 USDC, 2x (colateral = BTC, la API lo convierte)"
curl -s -m 30 -X POST https://perps-api.jup.ag/v1/positions/increase -H 'content-type: application/json' -d '{"walletAddress":"'$W'","marketMint":"3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh","inputMint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","collateralMint":"3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh","side":"long","leverage":"2","maxSlippageBps":"100","collateralTokenDelta":"10000000","includeSerializedTx":true,"tpsl":[]}' | python3 -c "
import json,sys
d=json.load(sys.stdin); q=d.get('quote') or {}
print('quote', {k:q.get(k) for k in ('entryPriceUsd','leverage','liquidationPriceUsd','openFeeUsd','priceImpactFeeUsd','positionSizeUsd')}, 'tx?', bool(d.get('serializedTxBase64')), 'keeper', d.get('requireKeeperSignature'), 'type', d.get('transactionType'))
if 'error' in d or 'message' in d: print('ERROR', d)
"
echo "--- decrease (no-gasless) existe?"
curl -s -m 20 -o /dev/null -w "positions/decrease %{http_code}\n" -X POST https://perps-api.jup.ag/v1/positions/decrease -H 'content-type: application/json' -d '{}'
curl -s -m 20 -w " positions-gasless/decrease %{http_code}\n" -X POST https://perps-api.jup.ag/v1/positions-gasless/decrease -H 'content-type: application/json' -d '{}' | head -c 300; echo
echo "--- velas de oráculo (SOL 1h, 3 últimas)"
curl -s -m 20 "https://history.oraclesecurity.org/trading-view/data?symbol=Crypto.SOL/USD&resolution=60&from=$(( $(date +%s) - 4*3600 ))&to=$(date +%s)" | head -c 400; echo
echo "--- saldo USDC de las billeteras de los planes"
for p in tradicional equilibrado agresivo; do python3 -c "
import json;d=json.load(open('state/plan__summary.json'));print('',d['wallet'],[ (x['symbol'],round(x['value_usd'])) for x in d['positions']],'sol',d['cash_sol'])"; done
