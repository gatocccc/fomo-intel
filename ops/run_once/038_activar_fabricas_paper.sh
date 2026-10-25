#!/bin/bash
# Activa la estrategia "fábricas" en SIMULADO con las fábricas que mostraron >=57% de acierto en el histórico. Archiva lo real.
cd /root/fomo_intel
systemctl stop fomo-live
python3 - <<'PY'
import json, os, shutil, time
devs = json.load(open("state/ops/creadores_st.json"))
want = ("gVDXhoGbeP", "9CV42qBfFa", "JDQKDrc1TQ", "4Lm2uqHgau", "B32QbbdDAy")
wallets = [d["dev"] for d in devs if d["dev"].startswith(want)]
json.dump({"wallets": wallets, "updated": time.time(), "nota": "fábricas con alta graduación; sim histórico TP1.5 en 3 min: gVDX 72%, 9CV4 61%, JDQK 57%, 4Lm2 55%; B32Q sin sim (29% graduación)"}, open("state/factories.json", "w"), indent=1)
print("fábricas:", wallets)
os.makedirs("state/real_archive", exist_ok=True); stamp = time.strftime("%Y%m%d_%H%M")
for f in ("closed.jsonl", "trades.jsonl", "positions.json", "live_summary.json"):
    if os.path.exists(f"state/{f}"): shutil.move(f"state/{f}", f"state/real_archive/{stamp}_{f}")
if os.path.exists("state/STOP"): os.remove("state/STOP")
p = "state/control.json"; d = json.load(open(p))
d.update({"mode": "paper", "strategy": "factory", "trading_enabled": True, "panic": False, "size_usd": 10.0, "max_open": 5,
          "daily_loss_usd": 50.0, "total_loss_usd": 150.0, "max_trades": 1000, "max_slippage_pct": 15.0,
          "factory_tp": 1.5, "factory_max_hold_s": 180, "factory_stop": 0.5, "factory_paper_wait_s": 2.0})
json.dump(d, open(p, "w"), indent=1)
env = [l for l in open(".env").read().splitlines() if not l.startswith("LIVE_MODE=")] + ["LIVE_MODE=paper"]
open(".env", "w").write("\n".join(env) + "\n")
print("control:", {k: d[k] for k in ("mode", "strategy", "size_usd", "max_open")})
PY
systemctl start fomo-live; sleep 5; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 3
