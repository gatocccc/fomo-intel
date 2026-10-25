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


def _tail(name: str, n: int = 400) -> list:
    f = STATE / name
    if not f.exists():
        return []
    out = []
    with open(f) as fh:
        for line in fh.read().splitlines()[-n:]:
            try: out.append(json.loads(line))
            except Exception: pass  # noqa: BLE001
    return out


def live_payload() -> dict:
    sess = {}
    try: sess = json.load(open(STATE / "session.json"))
    except Exception: pass  # noqa: BLE001
    start = float(sess.get("start", 0))
    try: summ = json.load(open(STATE / "live_summary.json"))
    except Exception: summ = {}
    try: ctrl = json.load(open(STATE / "control.json"))
    except Exception: ctrl = {}
    closed = [c for c in _tail("closed.jsonl", 500) if c.get("ts", 0) >= start]
    trades = [t for t in _tail("trades.jsonl", 800) if t.get("ts", 0) >= start and t.get("mode") == sess.get("mode", "real")]
    sigs = [x for x in _tail("signals.jsonl", 600) if x.get("ts", 0) >= start and x.get("strategy") == sess.get("strategy", ctrl.get("strategy"))]
    # feed de eventos: lanzamientos vistos, compras y ventas, del más nuevo al más viejo
    feed = []
    for x in sigs:
        feed.append({"ts": x["ts"], "tipo": "lanzamiento" if x.get("decision") != "COMPRADO" else "compra_ok", "token": x.get("symbol") or x.get("mint", "")[:6],
                     "mint": x.get("mint"), "fabrica": (x.get("creator") or "")[:6], "detalle": x.get("decision")})
    for t in trades:
        if t.get("side") == "sell" and t.get("ok"):
            feed.append({"ts": t["ts"], "tipo": "venta", "token": t.get("mint", "")[:6], "mint": t.get("mint"), "detalle": f"{t.get('why')} · {t.get('sol', 0):.4f} SOL"})
        elif not t.get("ok"):
            feed.append({"ts": t["ts"], "tipo": "error", "token": t.get("mint", "")[:6], "mint": t.get("mint"), "detalle": f"{t.get('side')} falló: {(t.get('error') or '')[:80]}"})
    feed.sort(key=lambda e: -e["ts"])
    buys = [t for t in trades if t.get("side") == "buy" and t.get("ok")]
    wins = [c for c in closed if c.get("pnl_usd", 0) > 0]
    return {"now": time.time(), "bot_ts": summ.get("ts"), "mode": summ.get("mode"), "strategy": summ.get("strategy"), "session_start": start,
            "start_sol": sess.get("start_sol"), "wallet_sol": summ.get("wallet_sol"), "sol_usd": summ.get("sol_usd"),
            "stop_reason": summ.get("stop_reason"), "stop_file": (STATE / "STOP").exists(), "panic": ctrl.get("panic"),
            "stream_ok": summ.get("stream_connected"), "helius_ok": (summ.get("helius") or {}).get("connected"),
            "factories": summ.get("factories"), "positions": summ.get("positions", []),
            "closed": closed[::-1][:30], "n_closed": len(closed), "n_wins": len(wins), "pnl_usd": round(sum(c.get("pnl_usd", 0) for c in closed), 2),
            "n_buys": len(buys), "avg_slip": round(sum(t.get("slippage_pct", 0) for t in buys) / len(buys), 1) if buys else None,
            "launches_seen": len(sigs), "feed": feed[:25],
            "rules": {k: ctrl.get(k) for k in ("size_usd", "max_open", "daily_loss_usd", "total_loss_usd", "factory_tp", "factory_max_hold_s", "factory_stop")}}


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/live"):
            return self._send(200, live_payload())
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
