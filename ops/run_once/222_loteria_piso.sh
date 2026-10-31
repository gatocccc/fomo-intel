#!/bin/bash
# 31/10 11:30 — "Lotería en el piso": prueba hacia adelante con billetera propia (secrets/plan_floor.json). OK de Gastón 11:01.
# 1) servicio fomo-floor, primero 3 min en sombra para validar lectura de la curva y tasa de elegibles; 2) queda en live
# (sin saldo no compra: arranca solo cuando Gastón deposita).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
mkdir -p state/desk
echo "--- otros usuarios del websocket de PumpPortal:"; systemctl is-active fomo-live 2>/dev/null; pgrep -af "tweet_shadow|live.bot" | head -3
echo shadow > state/desk/floor_mode
cat > /etc/systemd/system/fomo-floor.service <<UNIT
[Unit]
Description=Loteria en el piso (pump.fun primer minuto, billetera propia)
After=network.target
[Service]
WorkingDirectory=/root/fomo_intel
EnvironmentFile=/root/fomo_intel/.env
ExecStart=/usr/bin/python3 -u -m fomo_intel.desk.floor
Restart=always
RestartSec=15
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl enable -q --now fomo-floor; sleep 200
echo "fomo-floor: $(systemctl is-active fomo-floor)"
journalctl -u fomo-floor --no-pager -n 15
python3 -c "
import json;d=json.load(open('state/desk/floor.json'));print('BILLETERA', d['wallet']);print(json.dumps(d,indent=1)[:1200])"
echo "--- candidatos elegibles (muestra):"; tail -5 state/desk/floor_cands.jsonl; wc -l state/desk/floor_cands.jsonl
echo live > state/desk/floor_mode; echo "modo: $(cat state/desk/floor_mode)"
