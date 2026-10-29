#!/bin/bash
# ¿Cómo se manda la transacción "instant" que necesita firma del keeper? Sondeo de rutas con cuerpo vacío: un 400 con validación revela los campos; 404 = no existe.
cd /root/fomo_intel
for p in positions/execute positions/increase/execute positions-gasless/execute execute send positions/send transactions/execute positions/increase/send positions/submit submit positions/increase/submit; do
  printf "%-36s " "$p"; curl -s -m 15 -X POST "https://perps-api.jup.ag/v1/$p" -H 'content-type: application/json' -d '{}' -w " [%{http_code}]" | head -c 260; echo
done
echo "--- GET rutas informativas"
for p in "positions-gasless/status" "config" "markets" "tpsl?walletAddress=EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4" "trades?walletAddress=EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4"; do
  printf "%-60s " "$p"; curl -s -m 15 "https://perps-api.jup.ag/v1/$p" -w " [%{http_code}]" | head -c 200; echo
done
echo "--- increase con includeSerializedTx y tipo no-instant? (probar campo transactionType)"
curl -s -m 30 -X POST https://perps-api.jup.ag/v1/positions/increase -H 'content-type: application/json' -d '{"walletAddress":"EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4","marketMint":"So11111111111111111111111111111111111111112","inputMint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","collateralMint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","side":"short","leverage":"2","maxSlippageBps":"100","collateralTokenDelta":"10000000","includeSerializedTx":true,"tpsl":[],"transactionType":"market"}' | python3 -c "
import json,sys,base64
d=json.load(sys.stdin); print('keeper',d.get('requireKeeperSignature'),'type',d.get('transactionType'),'err',d.get('message'))
tx=d.get('serializedTxBase64')
if tx:
    raw=base64.b64decode(tx); print('bytes',len(raw),'firmas requeridas (primer byte)',raw[0])
"
echo "--- decodificar la tx instant: cuántas firmas pide y cuáles son los firmantes"
curl -s -m 30 -X POST https://perps-api.jup.ag/v1/positions/increase -H 'content-type: application/json' -d '{"walletAddress":"EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4","marketMint":"So11111111111111111111111111111111111111112","inputMint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","collateralMint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","side":"short","leverage":"2","maxSlippageBps":"100","collateralTokenDelta":"10000000","includeSerializedTx":true,"tpsl":[]}' | python3 -c "
import json,sys,base64
from solders.transaction import VersionedTransaction
d=json.load(sys.stdin); tx=VersionedTransaction.from_bytes(base64.b64decode(d['serializedTxBase64']))
h=tx.message.header; keys=tx.message.account_keys
print('firmas requeridas',h.num_required_signatures,'firmantes',[str(k) for k in keys[:h.num_required_signatures]])
print('firmas presentes', [str(s)[:12] for s in tx.signatures])
print('programas', sorted({str(keys[i.program_id_index]) for i in tx.message.instructions if i.program_id_index < len(keys)}))
"
