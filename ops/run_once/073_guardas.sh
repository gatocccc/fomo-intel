#!/bin/bash
# Guardas operativas (26/10): banco de rechazos por motivo, contadores de rechazos, salida sin datos / fuente caída,
# escalera de fallas (5 fallas de ejecución seguidas -> STOP). El código ya se desplegó (el sync reinicia fomo-live).
# Este op solo verifica que el bot arrancó bien con las guardas y muestra el estado.
cd /root/fomo_intel; set -a; . ./.env; set +a
sleep 20
systemctl is-active fomo-live
journalctl -u fomo-live --no-pager --since "-3 min" | grep -E "arranca|Traceback|Error|ALERTA" | tail -8
python3 -m pytest -q tests/test_guard.py 2>&1 | tail -2
python3 - <<'PY'
import json
s = json.load(open("state/live_summary.json"))
print("modo:", s.get("mode"), s.get("strategy"), "| abiertas:", s.get("open"), "| stop:", s.get("stop_reason"))
print("guardas:", json.dumps(s.get("guard"), ensure_ascii=False))
print("rechazos hoy:", json.dumps(s.get("rejections"), ensure_ascii=False))
c = json.load(open("state/control.json"))
print("params:", {k: c.get(k) for k in ("stale_exit_s", "exec_fail_halt", "exec_fail_window_s", "source_down_exit_s", "fast_sell_after", "bench_min")})
PY
