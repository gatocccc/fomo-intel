#!/bin/bash
cd /root/fomo_intel
python3 - <<'PY'
import json, time
f = json.load(open("state/factories.json")); f["wallets"] = [w for w in f["wallets"] if not w.startswith("B32QbbdD")]
f["nota"] = "25/10 17:40: fuera B32Q (vende todo en los 6 s posteriores a crear). Quedan gVDX y 9CV4."; f["updated"] = time.time()
json.dump(f, open("state/factories.json", "w"), indent=1); print(f["wallets"])
PY
systemctl restart fomo-live; sleep 4; systemctl is-active fomo-live
