#!/bin/bash
# Activa el modo seguidor (paper) con las billeteras copiables encontradas.
cd /root/fomo_intel
python3 - <<'PY'
import json, time
wallets = ["12DEB4G85cbQ3GPA7zC5KQ2bHjLt6JChZv9axQeqrf7a", "13mWvbz8wc1JvLFuvBHfpmhuQ29DRtsKkznXbnPuSdUm", "21gEdEoqCh1YXXb5fviqQRtZRpPaDtGrHGsmDoib9eak",
           "13fiXsw8ApBq28Qtq7iiqGJx8PoR246Q2B83rYWTo6d4", "13oSKUXKAUvvPaHLN1UQCzoWZkGGMmSPfRVPpSJiGczx", "E4FPggw9yDp9PNJDuRoLYDr6a5HKCsAterw3fygLpZEA",
           "43vXrgojAHoHDaQVhd7nnR8iUKtn1EDse3SCFue1PbjH", "6GjUxrxZd2dvCrXuLzaWshscLJCH5DAdQQpBsrux4uax"]
json.dump({"wallets": wallets, "updated": time.time()}, open("state/follow_list.json", "w"), indent=1)
p = "state/control.json"; d = json.load(open(p))
d.update({"strategy": "follow", "follow_max_hold_min": 1440, "follow_stop": 0.35, "follow_trail": 0.40, "follow_tp_mult": 3.0, "follow_min_sol": 0.05, "follow_max_mcap_sol": 3000, "max_open": 5})
json.dump(d, open(p, "w"), indent=1); print("control:", {k: d[k] for k in ("strategy", "mode", "size_usd", "max_open")})
PY
systemctl restart fomo-live; sleep 4; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 4
