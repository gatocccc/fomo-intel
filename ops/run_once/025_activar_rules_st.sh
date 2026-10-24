#!/bin/bash
cd /root/fomo_intel
python3 - <<'PY'
import json; p="state/control.json"; d=json.load(open(p))
d.update({"strategy": "rules_st", "max_open": 3, "size_usd": 10.0, "max_slippage_pct": 8.0}); json.dump(d, open(p,"w"), indent=1); print({k:d[k] for k in ("strategy","mode","max_open")})
PY
systemctl restart fomo-live; sleep 5; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 5
