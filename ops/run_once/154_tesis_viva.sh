#!/bin/bash
# Verifica la tesis viva del radar (30/10): que las posiciones abiertas tengan tesis, que el hecho inyectado (Binance cubre pérdidas)
# haya ajustado el stop del corto del libro, que Telegram entregue titulares y por qué el clasificador LLM no venía respondiendo.
cd /root/fomo_intel
sleep 90   # que el radar reinicie y corra un ciclo con el código nuevo
echo "--- servicio"; systemctl is-active fomo-radar
echo "--- paquete anthropic: $(python3 -c 'import anthropic; print(anthropic.__version__)' 2>&1 | tail -1)"
echo "--- prueba directa del modelo"; python3 - <<'PY'
import os, sys; sys.path.insert(0, ".")
from fomo_intel.live.bot import load_dotenv; load_dotenv()
try:
    import anthropic
    m = anthropic.Anthropic().messages.create(model=os.getenv("RADAR_LLM_MODEL", "claude-haiku-5-5"), max_tokens=20, messages=[{"role":"user","content":"Reply with the word ok"}])
    print("modelo responde:", m.content[0].text[:40])
except Exception as e:
    print("MODELO FALLA:", type(e).__name__, str(e)[:300])
PY
echo "--- radar.json: tesis, reglas, llm, fuentes"; python3 - <<'PY'
import json
d = json.load(open("state/desk/radar.json"))
print("llm:", d.get("llm")); print("fuentes vistas:", d.get("sources"))
for leg, p in (d.get("positions") or {}).items():
    if p: print(leg, "entrada", p["entry"], "mark", p.get("mark"), "stop_px", p.get("stop_px"), "be", p.get("be_armed"), "reglas", p.get("rules"), "tesis", (p.get("thesis") or {}).get("state"), [(e["verdict"], e["title"][:60]) for e in (p.get("thesis") or {}).get("evidence", [])])
PY
echo "--- log del radar (tesis/telegram)"; grep -E '"kind": "(thesis|breakeven_armed|close|open_failed|close_failed)"' state/desk/radar_log.jsonl | tail -8 | cut -c1-300
echo "--- journal"; journalctl -u fomo-radar --no-pager --since "-3 min" | grep -v httpx | tail -12 | cut -c1-220
