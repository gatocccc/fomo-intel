#!/bin/bash
# Verifica la tortuga 55/20 en la mesa (commit c8c35ecf): espera el reinicio de fomo-radar y muestra posiciones y logs.
cd /root/fomo_intel
sleep 150
systemctl is-active fomo-radar fomo-desk
git log -1 --format='%h %s' | cut -c1-80
echo "--- turtle_pos_desk"; cat state/desk/turtle_pos_desk.json 2>/dev/null || echo "(sin archivo)"
echo "--- joined"; cat state/desk/turtle_desk_joined.json 2>/dev/null
echo "--- radar_log turtle"; grep '"turtle_' state/desk/radar_log.jsonl | tail -4 | cut -c1-400
echo "--- journal radar"; journalctl -u fomo-radar --since "-6 min" --no-pager | grep -i "turtle\|error\|Traceback" | tail -15
echo "--- mesa auto"; ls -t state/desk/auto | head -3
echo "--- perps on-chain mesa"; set -a; . ./.env; set +a
W=$(python3 -c "import json,sys;sys.path.insert(0,'.');from fomo_intel.live.config import Env;print(json.load(open(Env().wallet_file))['pubkey'])" 2>/dev/null); echo "wallet $W"
curl -s "https://perps-api.jup.ag/v1/positions?walletAddress=$W" | head -c 800; echo
sleep 60
echo "--- mesa summary"; python3 -c "
import json;d=json.load(open('state/desk_summary.json'))
print(d['equity_usd'],[(p['symbol'],p.get('value_usd')) for p in d['positions']])"
