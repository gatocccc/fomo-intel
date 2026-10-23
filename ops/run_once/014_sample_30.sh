#!/bin/bash
cd /root/fomo_intel
python3 - <<'PY'
import json; p="state/control.json"; d=json.load(open(p)); d["stream_sample"]=0.3; d["stream_watch_s"]=150; json.dump(d, open(p,"w"), indent=1); print(d["stream_sample"])
PY
systemctl restart fomo-live; sleep 3; systemctl is-active fomo-live
