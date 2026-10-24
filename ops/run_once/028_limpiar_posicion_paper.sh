#!/bin/bash
# El proceso viejo reescribió positions.json al apagarse: quedó una posición SIMULADA (DBB) en modo real. Se quita y se limpia su rastro.
cd /root/fomo_intel
systemctl stop fomo-live
python3 - <<'PY'
import json, os
p = "state/positions.json"
if os.path.exists(p):
    d = json.load(open(p)); print("posiciones encontradas:", list(d)); json.dump({}, open(p, "w"))
for f in ("state/closed.jsonl", "state/trades.jsonl"):
    if os.path.exists(f):
        rows = [l for l in open(f) if l.strip()]
        keep = [l for l in rows if '"mode": "paper"' not in l and '"sig": "paper-' not in l and "sin tokens" not in l and "DBB" not in l]
        open(f, "w").write("".join(keep)); print(f, len(rows), "->", len(keep))
PY
systemctl start fomo-live; sleep 5; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 3
