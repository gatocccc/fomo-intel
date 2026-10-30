#!/bin/bash
# 30/10: (1) por qué el servicio del radar no ve ANTHROPIC_API_KEY aunque el .env sí la tiene para los ops; si falta en .env y está en el
# entorno del runner, la agrega al .env (600) y reinicia el radar; (2) verifica que la tesis del corto del libro se haya re-evaluado.
cd /root/fomo_intel
echo "--- clave en .env: $(grep -c '^ANTHROPIC_API_KEY=' .env) líneas; con export: $(grep -c 'export ANTHROPIC_API_KEY' .env); en el entorno del runner: $([ -n "$ANTHROPIC_API_KEY" ] && echo si || echo no)"
echo "--- otros lugares:"; grep -ls ANTHROPIC_API_KEY /root/.bashrc /root/.profile /etc/environment /etc/systemd/system/*.service /etc/cron.d/* /var/spool/cron/crontabs/* 2>/dev/null
PID=$(systemctl show -p MainPID --value fomo-radar); echo "--- en el proceso del radar: $(tr '\0' '\n' < /proc/$PID/environ 2>/dev/null | grep -c '^ANTHROPIC_API_KEY=.')"
if ! grep -q '^ANTHROPIC_API_KEY=.' .env && [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" >> .env; chmod 600 .env; echo "clave agregada al .env"
fi
systemctl restart fomo-radar; sleep 100
echo "--- radar.json"; python3 - <<'PY'
import json
d = json.load(open("state/desk/radar.json"))
print("llm:", d.get("llm"))
for leg, p in (d.get("positions") or {}).items():
    if p: print(leg, "entrada", p["entry"], "mark", p.get("mark"), "stop_px", p.get("stop_px"), "be", p.get("be_armed"), "reglas", p.get("rules"), "tesis", (p.get("thesis") or {}).get("state"), (p.get("thesis") or {}).get("entities"), [(e["verdict"], e["by"], e["title"][:60]) for e in (p.get("thesis") or {}).get("evidence", [])])
PY
echo "--- log"; grep -E '"kind": "(thesis|breakeven_armed|close|open)"' state/desk/radar_log.jsonl | tail -6 | cut -c1-260
echo "--- journal"; journalctl -u fomo-radar --no-pager --since "-2 min" | grep -v -E "httpx|evento \[" | tail -10 | cut -c1-220
