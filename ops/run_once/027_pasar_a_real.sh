#!/bin/bash
# Pase a DINERO REAL (pedido explícito de Gastón 24/10 13:06 ART). Archiva lo simulado, fija frenos, cambia modo y reinicia.
cd /root/fomo_intel; set -a; . ./.env; set +a
SALDO=$(python3 -c "
import json; from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
print(Rpc(Env().rpc_url).sol_balance(json.load(open('state/wallet_pub.json'))['pubkey']))")
echo "saldo bot: $SALDO SOL"
python3 - "$SALDO" <<'PY'
import json, os, shutil, sys, time
saldo = float(sys.argv[1])
if saldo < 0.3:
    print("SALDO INSUFICIENTE: no se pasa a real"); sys.exit(1)
os.makedirs("state/paper_archive", exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M")
for f in ("closed.jsonl", "trades.jsonl", "positions.json", "live_summary.json"):
    if os.path.exists(f"state/{f}"):
        shutil.move(f"state/{f}", f"state/paper_archive/{stamp}_{f}")
shutil.copy("state/signals.jsonl", f"state/paper_archive/{stamp}_signals.jsonl")
if os.path.exists("state/STOP"): os.remove("state/STOP")
p = "state/control.json"; d = json.load(open(p))
d.update({"mode": "real", "strategy": "rules_st", "trading_enabled": True, "panic": False, "size_usd": 10.0, "max_open": 3,
          "daily_loss_usd": 50.0, "total_loss_usd": 150.0, "max_trades": 30, "max_slippage_pct": 8.0, "swap_slippage_pct": 10.0,
          "priority_fee_sol": 0.0005, "min_sol_reserve": 0.03})
json.dump(d, open(p, "w"), indent=1)
env = open(".env").read().splitlines()
env = [l for l in env if not l.startswith("LIVE_MODE=")] + ["LIVE_MODE=real"]
open(".env", "w").write("\n".join(env) + "\n")
print("control:", {k: d[k] for k in ("mode", "strategy", "size_usd", "max_open", "daily_loss_usd", "total_loss_usd", "max_trades")})
PY
[ $? -eq 0 ] || exit 1
systemctl restart fomo-live; sleep 6; systemctl is-active fomo-live
journalctl -u fomo-live --no-pager -n 4
