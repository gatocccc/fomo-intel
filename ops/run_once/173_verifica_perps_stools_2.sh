#!/bin/bash
# 30/10 — segunda verificación: colateral en dólares (no unidades crudas), corto de SOL copiado en todos los stools, cash positivo.
cd /root/fomo_intel || exit 1
sleep 120
python3 - <<'PY'
import json, glob, os
s = json.load(open("state/plan_lloyd_summary.json")); print("libro eq", s.get("equity_usd"), [(p.get("symbol"), p.get("value_usd")) for p in s.get("positions", [])])
for f in sorted(glob.glob("state/users/*_summary.json")):
    s = json.load(open(f)); uid = s.get("user_id")
    perps = json.load(open(f"state/users/{uid}/perps.json")) if os.path.exists(f"state/users/{uid}/perps.json") else {}
    if not s.get("started"): continue
    print(f"[{uid}] eq={s.get('equity_usd')} cash={s.get('cash_usd')} perps_open={s.get('perps_open')} pnl={s.get('pnl_usd')}")
    for k, p in perps.items():
        print(f"     {k}: coll={p.get('collateral_usd')} size={p.get('size_usd')} entry={p.get('entry')} pnl={p.get('pnl_usd')} err={p.get('error')}")
    for r in [json.loads(l) for l in open(f"state/users/{uid}/skipped.jsonl")][-3:] if os.path.exists(f"state/users/{uid}/skipped.jsonl") else []:
        print("     skipped:", r)
PY
echo "== mirror log =="; journalctl -u fomo-mirror --no-pager -n 40 2>&1 | grep -v systemd | tail -40
