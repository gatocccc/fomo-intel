#!/bin/bash
# 30/10 06:40 UTC (sesión autónoma): (1) reinicia radar y cerebro para tomar el parser JSON robusto del modelo y el texto correcto
# del motivo de defensa; (2) diagnóstico de SAFU en el lab (venta por PumpPortal falla, sin precio desde hace horas);
# (3) estado de los dos candidatos con motivo de la lista (GTA6, REMUS): precio, retroceso y anti-rug.
cd /root/fomo_intel
systemctl restart fomo-radar fomo-brain; sleep 90
echo "--- radar llm"; python3 -c "import json;d=json.load(open('state/desk/radar.json'));print(d.get('llm'), d.get('bear_score'), (d.get('shock') or {}).get('since'))"
echo "--- SAFU dexscreener"; curl -s https://api.dexscreener.com/latest/dex/tokens/A8aDT3aAzS5b27GfT9dsXchqAkY9o6ACmvAEf2R2E9it | python3 -c "
import json,sys;d=json.load(sys.stdin);ps=d.get('pairs') or [];print('pares',len(ps))
for p in ps[:4]: print(p['dexId'],p.get('priceUsd'),(p.get('liquidity') or {}).get('usd'),(p.get('volume') or {}).get('h24'))"
echo "--- SAFU Jupiter quote (todo el saldo → SOL)"; curl -s "https://lite-api.jup.ag/swap/v1/quote?inputMint=A8aDT3aAzS5b27GfT9dsXchqAkY9o6ACmvAEf2R2E9it&outputMint=So11111111111111111111111111111111111111112&amount=152994000000&slippageBps=1500" | head -c 400; echo
echo "--- candidatos con motivo"
for m in 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz CA8q2mkYWZnUNqYmf6pxyxAPZsmSe2EG9P7hHMW5pump; do
curl -s https://api.dexscreener.com/latest/dex/tokens/$m | python3 -c "
import json,sys;ps=json.load(sys.stdin).get('pairs') or []
p=max(ps,key=lambda p:(p.get('liquidity') or {}).get('usd',0)) if ps else None
print(p and (p['baseToken']['symbol'],p.get('priceUsd'),'mcap',p.get('marketCap'),'liq',(p.get('liquidity') or {}).get('usd'),'ch',p.get('priceChange'),'vol24',(p.get('volume') or {}).get('h24')))"
done
timeout 600 python3 -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz CA8q2mkYWZnUNqYmf6pxyxAPZsmSe2EG9P7hHMW5pump 2>&1 | tail -25
echo "--- cerebro"; journalctl -u fomo-brain --no-pager --since "-2 min" | tail -5 | cut -c1-220
