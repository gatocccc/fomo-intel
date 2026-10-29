#!/bin/bash
# 29/10 noche: (1) post-mortem por motivo de compra, (2) radar de noticias como servicio con cortos REALES desde el laboratorio,
# (3) verificación de la venta de JOB/DOPE y de la lista de seguimiento.
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "--- claves disponibles: ANTHROPIC=$([ -n "$ANTHROPIC_API_KEY" ] && echo si || echo no) CRYPTOPANIC=$([ -n "$CRYPTOPANIC_TOKEN" ] && echo si || echo no) X=$([ -n "$X_BEARER_TOKEN" ] && echo si || echo no)"
echo "--- post-mortem"
python3 -m fomo_intel.desk.postmortem
echo "--- radar (una pasada, en sombra, para ver qué detecta ahora)"
RADAR_PERPS=shadow timeout 240 python3 -m fomo_intel.desk.radar --once 2>&1 | tail -25
python3 -c "import json;d=json.load(open('state/desk/radar.json'));print('shock:',json.dumps(d.get('shock'))[:400]);print('bear',d.get('bear_score'),'bull',d.get('bull_score'));print('price',json.dumps(d.get('price')));[print(' ',e['sev'],e['dir'],e['src'],e['title'][:90]) for e in d.get('events',[])[:12]]"
echo "--- servicio fomo-radar (cortos reales desde el laboratorio)"
cat > /etc/systemd/system/fomo-radar.service <<UNIT
[Unit]
Description=FOMO news radar (noticias + confirmacion de precio + cortos chicos en Jupiter Perps)
After=network.target
[Service]
WorkingDirectory=/root/fomo_intel
EnvironmentFile=/root/fomo_intel/.env
Environment=RADAR_PERPS=live
Environment=RADAR_WALLET=secrets/plan_lab.json
Environment=RADAR_PLAN=lab
ExecStart=/usr/bin/python3 -m fomo_intel.desk.radar
Restart=always
RestartSec=15
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl enable -q --now fomo-radar; sleep 5; echo "fomo-radar: $(systemctl is-active fomo-radar)"
echo "--- lab: USDC y SOL"
sleep 60
python3 - <<'PY'
import json
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.live.config import Env
from fomo_intel.live.wallet import Rpc, load_or_create
from pathlib import Path
kp = load_or_create(Path("secrets/plan_lab.json")); rpc = Rpc(Env().rpc_url); w = str(kp.pubkey())
raw, dec = rpc.token_balance(w, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
print("lab", w, "SOL", round(rpc.sol_balance(w), 4), "USDC", raw / 10**dec)
for f in ("state/desk_summary.json", "state/plan_lloyd_summary.json", "state/plan_lab_summary.json"):
    s = json.load(open(f)); print(f, "eq", s.get("equity_usd"), "pos", [(p["symbol"], p.get("mult")) for p in s.get("positions", [])])
    for j in s.get("journal", [])[:4]: print("   ", j.get("title"), "|", (j.get("text") or "")[:160].replace("\n", " "))
PY
echo "--- regime / categorias"; cat state/desk/regime.json; python3 -c "import json;c=json.load(open('state/desk/categories.json'));print({k:v['status'] for k,v in c.items()})"
journalctl -u fomo-radar --no-pager -n 20
