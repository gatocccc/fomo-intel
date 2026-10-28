#!/bin/bash
cd /root/fomo_intel
journalctl -u fomo-brain --no-pager --since "-40 min" | tail -15
python3 - <<'PY'
import json,time
d=json.load(open("state/desk/scan_fast.json"))
print("escaneo rápido hace",round((time.time()-d["ts"])/60),"min · pasan filtros base:",len(d["ok"]),"· con velas:",len(d["all"]))
for v in d["ok"][:15]:
    dd=json.load(open(f"state/desk/dd/{v['mint']}.json")) if __import__("os").path.exists(f"state/desk/dd/{v['mint']}.json") else {}
    print(f"{(v['sym'] or '')[:10]:10s} ${v['mcap']/1e6:.2f}M liq ${v['liq']/1e3:.0f}K vol {v['vol_mcap']:.1f}x 1h {v['ch1h']:+.0%} 6h {v['ch6h']:+.0%} 24h {v['ch24h']:+.0%} máx {v['from_hi']:.0%} hold {v['holders']} top10 {v['top10']} dd {dd.get('verdict','-')}")
PY
