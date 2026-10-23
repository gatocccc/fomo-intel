"""Mini API de control para el dashboard (detrás del basic auth de nginx, solo en 127.0.0.1:8765).

POST /api/stop     -> crea state/STOP (no se abren posiciones nuevas)
POST /api/resume   -> borra state/STOP
POST /api/panic    -> control.json panic=true (vende todo, no abre nada)
POST /api/unpanic  -> control.json panic=false
GET  /api/status   -> state/live_summary.json
"""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATE = Path(os.getenv("FOMO_STATE_DIR", "state"))


def _control(**changes) -> dict:
    f = STATE / "control.json"
    d = json.load(open(f)) if f.exists() else {}
    d.update(changes)
    tmp = f.with_suffix(".tmp"); json.dump(d, open(tmp, "w"), indent=1); tmp.replace(f)
    return d


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            f = STATE / "live_summary.json"
            return self._send(200, json.load(open(f)) if f.exists() else {})
        self._send(404, {"msg": "no existe"})

    def do_POST(self):
        p = self.path.split("?")[0]
        stop = STATE / "STOP"
        if p == "/api/stop":
            stop.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} STOP manual desde el dashboard\n")
            return self._send(200, {"msg": "Compras frenadas. Las posiciones abiertas se siguen gestionando."})
        if p == "/api/resume":
            if stop.exists(): stop.unlink()
            return self._send(200, {"msg": "Bot rearmado: vuelve a abrir posiciones."})
        if p == "/api/panic":
            _control(panic=True)
            return self._send(200, {"msg": "Pánico activado: vende todo en el próximo ciclo y no abre nada."})
        if p == "/api/unpanic":
            _control(panic=False)
            return self._send(200, {"msg": "Pánico desactivado."})
        self._send(404, {"msg": "acción desconocida"})

    def log_message(self, fmt, *args):  # silencio en journal salvo errores
        pass


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    HTTPServer(("127.0.0.1", int(os.getenv("FOMO_CONTROL_PORT", "8765"))), H).serve_forever()


if __name__ == "__main__":
    main()
