#!/bin/bash
# 30/10 — verificación tras el despliegue de: (a) stools que copian las perps del libro, (b) estado "waiting for funds" corregido,
# (c) panel con las posiciones de la tortuga. Espera a que fomo-mirror y fomo-desk@lloyd hagan un par de ciclos y vuelca el estado.
cd /root/fomo_intel || exit 1
sleep 100
echo "== servicios =="
for s in fomo-mirror fomo-desk@lloyd fomo-app fomo-radar fomo-brain; do printf "%-18s %s\n" "$s" "$(systemctl is-active $s 2>&1)"; done
echo; echo "== libro: posiciones publicadas (plan_lloyd_summary.json) =="
python3 - <<'EOF'
import json
s = json.load(open("state/plan_lloyd_summary.json"))
print("equity", s.get("equity_usd"), "perps_pnl", s.get("perps_pnl_usd"))
for p in s.get("positions", []):
    print(f"  {p.get('symbol'):>22} sleeve={p.get('sleeve')} value={p.get('value_usd')} perps={p.get('perps')} mult={p.get('mult')}")
EOF
echo; echo "== perps del libro en cadena (Jupiter) =="
set -a; . ./.env; set +a
timeout 60 python3 scripts/perps_probe.py positions 2>&1 | head -40
echo; echo "== stools =="
python3 - <<'EOF'
import json, glob, os
for f in sorted(glob.glob("state/users/*_summary.json")):
    s = json.load(open(f)); uid = s.get("user_id")
    perps = json.load(open(f"state/users/{uid}/perps.json")) if os.path.exists(f"state/users/{uid}/perps.json") else {}
    print(f"[{uid}] {s.get('wallet')} started={s.get('started')} since={s.get('since')} eq={s.get('equity_usd')} cash={s.get('cash_usd')} perps_open={s.get('perps_open')}")
    for k, p in perps.items():
        print(f"     {k}: coll={p.get('collateral_usd')} pubkey={p.get('pubkey')} entry={p.get('entry')} pnl={p.get('pnl_usd')} err={p.get('error')}")
    for j in (s.get("journal") or [])[:4]:
        print("     ·", j.get("title"), "—", (j.get("text") or "")[:110].replace("\n", " "))
EOF
echo; echo "== /api/admin/wallets (started/equity) =="
python3 - <<'EOF'
import sys; sys.path.insert(0, ".")
from fomo_intel.app.server import trading_wallets
for w in trading_wallets():
    print(f"  {str(w.get('owner')):>16} started={w.get('started')} eq={w.get('equity_usd')} open={w.get('open')} pnl={w.get('pnl_usd')}")
EOF
echo; echo "== mirror log =="
journalctl -u fomo-mirror --no-pager -n 60 2>&1 | tail -60
echo; echo "== desk lloyd log =="
journalctl -u fomo-desk@lloyd --no-pager -n 25 2>&1 | tail -25
