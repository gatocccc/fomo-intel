#!/bin/bash
# 30/10 09:45 UTC (sesión autónoma 06:39 ART): (1) el radar toma el vencimiento del shock sin precio (max_stale_h=6);
# (2) estado del shock y del régimen tras el cambio; (3) GTA6 (único candidato con motivo): precio, retroceso y anti-rug con claves.
cd /root/fomo_intel
set -a; . ./.env; set +a
sleep 100
echo "--- radar"; python3 -c "import json;d=json.load(open('state/desk/radar.json'));sh=d.get('shock');print('shock',sh and {k:sh.get(k) for k in ('since','last_conf_ts','confirmed')}, 'last_shock_until', (d.get('last_shock') or {}).get('until'), d.get('llm'), d.get('price',{}).get('SOL'))"
grep shock_off state/desk/radar_log.jsonl | tail -2
echo "--- GTA6"
curl -s https://api.dexscreener.com/latest/dex/tokens/4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz | python3 -c "
import json,sys;ps=json.load(sys.stdin).get('pairs') or []
p=max(ps,key=lambda p:(p.get('liquidity') or {}).get('usd',0)) if ps else None
print(p and (p.get('priceUsd'),'mcap',p.get('marketCap'),'liq',(p.get('liquidity') or {}).get('usd'),'ch',p.get('priceChange'),'vol',p.get('volume'),'txns24',(p.get('txns') or {}).get('h24')))"
timeout 400 python3 -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 2>&1 | tail -15
echo "--- cerebro"; sleep 60; python3 -c "import json;print(json.load(open('state/desk/regime.json')))"; journalctl -u fomo-brain --no-pager --since "-12 min" | tail -6 | cut -c1-260
