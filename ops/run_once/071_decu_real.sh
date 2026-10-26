#!/bin/bash
# Copia de decu con DINERO REAL (pedido explícito de Gastón 26/10 07:49 ART: "hagamos decu con dinero real").
# decu: sniper pump.fun, compra a ~US$3K de mcap, vende a ~1,6 min; +32,6% por dólar en 3 días (ops 066).
# US$10 por copia, máx 3 abiertas, sale cuando decu vende (o stop -35% / 15 min). Corte: -US$50 total, -US$30 por día, 100 operaciones.
cd /root/fomo_intel; set -a; . ./.env; set +a
SALDO=$(python3 -c "
import json; from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
print(Rpc(Env().rpc_url).sol_balance(json.load(open('state/wallet_pub.json'))['pubkey']))")
echo "saldo bot: $SALDO SOL"
systemctl stop fomo-live
python3 - "$SALDO" <<'PY'
import json, os, shutil, sys, time
saldo = float(sys.argv[1])
if saldo < 0.4: print("SALDO INSUFICIENTE"); sys.exit(1)
if json.load(open("state/positions.json")) if os.path.exists("state/positions.json") else {}:
    print("HAY POSICIONES ABIERTAS: no cambio nada"); sys.exit(1)
os.makedirs("state/paper_archive", exist_ok=True); stamp = time.strftime("%Y%m%d_%H%M")
for f in ("closed.jsonl", "trades.jsonl", "positions.json", "live_summary.json", "signals.jsonl"):
    if os.path.exists(f"state/{f}"): shutil.move(f"state/{f}", f"state/paper_archive/{stamp}_{f}")
if os.path.exists("state/STOP"): os.remove("state/STOP")
json.dump({"wallets": ["4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"], "updated": time.time(),
           "nota": "decu (tweet GMB_XBT 25/10), copia real desde 26/10"}, open("state/follow_list.json", "w"), indent=1)
p = "state/control.json"; d = json.load(open(p))
d.update({"mode": "real", "strategy": "follow", "trading_enabled": True, "panic": False,
          "size_usd": 10.0, "max_open": 3, "daily_loss_usd": 30.0, "total_loss_usd": 50.0, "max_trades": 100,
          "max_slippage_pct": 25.0, "swap_slippage_pct": 25.0, "priority_fee_sol": 0.002, "min_sol_reserve": 0.05,
          "follow_min_sol": 0.05, "follow_exit_on_sell": True, "follow_stop": 0.35, "follow_trail": 0.40,
          "follow_tp_mult": 3.0, "follow_max_hold_min": 15, "follow_min_mcap_sol": 10.0, "follow_max_mcap_sol": 1500.0,
          "follow_min_wallets": 1})
json.dump(d, open(p, "w"), indent=1)
env = [l for l in open(".env").read().splitlines() if not l.startswith("LIVE_MODE=")] + ["LIVE_MODE=real"]
open(".env", "w").write("\n".join(env) + "\n")
json.dump({"start": time.time(), "start_sol": round(saldo, 4), "mode": "real", "strategy": "follow",
           "nota": "copia de decu con dinero real"}, open("state/session.json", "w"), indent=1)
print("control:", {k: d[k] for k in ("mode", "strategy", "size_usd", "max_open", "daily_loss_usd", "total_loss_usd", "max_trades",
                                     "follow_min_mcap_sol", "follow_max_hold_min", "follow_stop")})
PY
[ $? -eq 0 ] || { systemctl start fomo-live; exit 1; }
systemctl start fomo-live; sleep 8; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 6
