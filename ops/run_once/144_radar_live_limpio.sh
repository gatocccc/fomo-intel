#!/bin/bash
# La pasada de prueba en sombra (ops 143) dejó una posición "shadow" en state/desk/radar_pos.json y el servicio real la hereda y no abre.
# Se borra esa posición de sombra (se registra su cierre como shadow) y se reinicia el radar en modo real.
cd /root/fomo_intel; set -a; . ./.env; set +a
sleep 15
python3 - <<'PY'
import json, time
from pathlib import Path
p = Path("state/desk/radar_pos.json")
if p.exists():
    pos = json.load(open(p))
    if pos.get("mode") == "shadow":
        with open("state/desk/radar_log.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": "shadow_pos_discarded", **pos}) + "\n")
        p.unlink(); print("posición shadow descartada:", pos.get("entry"))
    else:
        print("posición real presente, no toco:", pos)
PY
systemctl restart fomo-radar; sleep 100
journalctl -u fomo-radar --no-pager -n 25 | grep -v httpx
echo "--- radar.json"; python3 -c "import json;d=json.load(open('state/desk/radar.json'));print('shock',bool(d.get('shock')),'pos',json.dumps(d.get('position'))[:500])"
echo "--- lab"; python3 -c "import json;s=json.load(open('state/plan_lab_summary.json'));print('eq',s.get('equity_usd'));[print('  ',j.get('title'),'|',(j.get('text') or '')[:200]) for j in s.get('journal',[])[:3]]"
