#!/bin/bash
# Pase a DINERO REAL de la estrategia fábricas (pedido explícito de Gastón 25/10 14:57 ART: "si lo perdemos no hay problema").
cd /root/fomo_intel; set -a; . ./.env; set +a
SALDO=$(python3 -c "
import json; from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
print(Rpc(Env().rpc_url).sol_balance(json.load(open('state/wallet_pub.json'))['pubkey']))")
echo "saldo bot: $SALDO SOL"
systemctl stop fomo-live
python3 - "$SALDO" <<'PY'
import json, os, shutil, sys, time
saldo = float(sys.argv[1])
if saldo < 0.3: print("SALDO INSUFICIENTE"); sys.exit(1)
os.makedirs("state/paper_archive", exist_ok=True); stamp = time.strftime("%Y%m%d_%H%M")
for f in ("closed.jsonl", "trades.jsonl", "positions.json", "live_summary.json"):
    if os.path.exists(f"state/{f}"): shutil.move(f"state/{f}", f"state/paper_archive/{stamp}_{f}")
if os.path.exists("state/STOP"): os.remove("state/STOP")
p = "state/control.json"; d = json.load(open(p))
d.update({"mode": "real", "strategy": "factory", "trading_enabled": True, "panic": False, "size_usd": 10.0, "max_open": 3,
          "daily_loss_usd": 50.0, "total_loss_usd": 120.0, "max_trades": 1000, "max_slippage_pct": 20.0, "swap_slippage_pct": 15.0,
          "priority_fee_sol": 0.001, "min_sol_reserve": 0.03, "factory_tp": 1.5, "factory_max_hold_s": 180, "factory_stop": 0.5})
json.dump(d, open(p, "w"), indent=1)
env = [l for l in open(".env").read().splitlines() if not l.startswith("LIVE_MODE=")] + ["LIVE_MODE=real"]
open(".env", "w").write("\n".join(env) + "\n")
print("control:", {k: d[k] for k in ("mode", "strategy", "size_usd", "max_open", "daily_loss_usd", "total_loss_usd", "factory_tp", "factory_max_hold_s")})
PY
[ $? -eq 0 ] || { systemctl start fomo-live; exit 1; }
systemctl start fomo-live; sleep 6; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 4
