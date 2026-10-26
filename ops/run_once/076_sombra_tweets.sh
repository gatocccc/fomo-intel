#!/bin/bash
# Modo sombra (sin plata): registra cada token nuevo de pump.fun con su link de X y la latencia para leerlo, durante 12 h.
# Objetivo: comparar los tokens "de tweet" que compra decu vs los que no compra, y simular entrar ANTES que él (segundo 2-5).
cd /root/fomo_intel; set -a; . ./.env; set +a
mkdir -p state/tweetshadow
nohup timeout 44000 python3 -u -m fomo_intel.experiments.tweet_shadow 43200 > state/ops/076_detalle.txt 2>&1 &
sleep 60
echo "pid $!"; wc -l state/tweetshadow/creates.jsonl
python3 - <<'PY'
import json
rows=[json.loads(l) for l in open("state/tweetshadow/creates.jsonl")]
n=len(rows); tw=[r for r in rows if r["is_tweet"]]
print(f"1 min: {n} creados, {len(tw)} con tweet, metadatos ok {sum(1 for r in rows if not r['meta_src'].startswith('fail'))}/{n}")
lat=sorted(r["meta_lat_s"] for r in rows); print("latencia metadatos mediana", lat[len(lat)//2] if lat else None)
for r in tw[:5]: print(r["symbol"], r["twitter"], r.get("tweet_to_create_s"), r["meta_src"])
PY
