#!/bin/bash
# Ajuste por datos (399-517 lanzamientos): TP 3x en 3 min, stop amplio 70%, solo las 3 fábricas con resultado positivo claro.
cd /root/fomo_intel
python3 - <<'PY'
import json, time
f = json.load(open("state/factories.json"))
keep = [w for w in f["wallets"] if w.startswith(("gVDXhoGb", "B32QbbdD", "9CV42qBf"))]
json.dump({"wallets": keep, "updated": time.time(), "nota": "25/10: fuera JDQK y 4Lm2 (24-38% acierto). gVDX TP3/3min: 74%, +0.79/op; B32Q 49%, +0.43; 9CV4 44%, +0.35"}, open("state/factories.json", "w"), indent=1)
p = "state/control.json"; d = json.load(open(p))
d.update({"factory_tp": 3.0, "factory_max_hold_s": 180, "factory_stop": 0.7})
json.dump(d, open(p, "w"), indent=1)
print("fábricas:", keep); print({k: d[k] for k in ("mode", "strategy", "factory_tp", "factory_max_hold_s", "factory_stop", "size_usd", "max_open")})
PY
systemctl restart fomo-live; sleep 5; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 2
