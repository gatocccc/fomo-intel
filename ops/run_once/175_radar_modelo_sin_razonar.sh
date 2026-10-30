#!/bin/bash
# 30/10 16:30 UTC (sesión autónoma): el juez de la tesis viva fallaba con stop_reason=max_tokens (el modelo razonaba y no
# escribía el JSON) → todo el shock de Binance se juzgó por palabras clave. Reinicia el radar con la consulta sin razonamiento
# extendido y 1.500 tokens; verifica que el modelo vuelva a contestar.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 60 python3 -c "
from fomo_intel.desk import radar
print('classify:', radar.classify_llm('Binance hit by \$6.3B hack, the largest in cryptocurrency history'))
print('thesis:', radar.thesis_llm({'claim':'SOL falls while Binance hack is confirmed'}, 'Binance says it will cover all losses from the hack'))
print('err:', radar._llm_err, 'nothink_ok:', radar._llm_nothink_ok)"
systemctl restart fomo-radar; sleep 120
python3 -c "
import json;d=json.load(open('state/desk/radar.json'))
print('llm', d.get('llm')); t=(d.get('theses') or {}).get('book') or {}
print('state', t.get('state'), 'rules', t.get('rules'))
for e in (t.get('evidence') or [])[-6:]: print(' ', e.get('verdict'), e.get('by'), e.get('title','')[:90])
print('book pos', (d.get('positions') or {}).get('book') and 'abierta')"
journalctl -u fomo-radar --no-pager --since "-3 min" | tail -8 | cut -c1-220
