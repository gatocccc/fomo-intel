#!/bin/bash
# Umbral del cazador al percentil 99 del VIVO (0,27) para juntar ~10 entradas/h en papel. Sigue en papel.
cd /root/fomo_intel
python3 - <<'PY'
import json; p="state/tweetsniper/control.json"; c=json.load(open(p)); c["threshold"]=0.27; json.dump(c,open(p,"w"),indent=1); print(c)
PY
