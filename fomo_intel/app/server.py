"""API del piloto automático (landing pública + panel de administración).

Escucha en 127.0.0.1:8770, detrás de nginx (app.nonconformistducks.com).
  GET  /api/semaforo?objetivo=2&dias=30   -> chances por plan
  GET  /api/publico                        -> historial en vivo de la mesa (sin datos sensibles)
  GET  /api/holder/mensaje?eth=0x...       -> mensaje para firmar con la billetera de Ethereum
  POST /api/aplicar                        -> guarda una aplicación (state/app/aplicaciones.jsonl)
  GET  /api/admin/resumen                  -> panel (nginx le pone basic auth a /api/admin/ y /admin/)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from fomo_intel.app.semaforo import PLANS, semaforo

STATE = Path(os.getenv("FOMO_STATE_DIR", "state"))
APP = STATE / "app"
APP.mkdir(parents=True, exist_ok=True)
APLIC = APP / "aplicaciones.jsonl"
PORT = int(os.getenv("APP_PORT", "8770"))
ETH_RPC = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
# Contratos de NoncoDucks que habilitan el beneficio de holder (separados por coma). Sin configurar: queda "a verificar".
NONCO_CONTRACTS = [c.strip().lower() for c in os.getenv("NONCO_CONTRACTS", "").split(",") if c.strip()]
FEES = {"por_operacion": float(os.getenv("FEE_TRADE_PCT", "0.5")), "exito_externos": float(os.getenv("FEE_SUCCESS_PCT", "10"))}
SOL_RPC = os.getenv("SOLANA_RPC_URL") or f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY', '')}"

_lock = threading.Lock()
_nonces: dict[str, tuple[str, float]] = {}
_hits: dict[str, list[float]] = {}
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
ETH = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _rate_ok(ip: str, limit: int = 8, window: int = 3600) -> bool:
    now = time.time()
    with _lock:
        h = [t for t in _hits.get(ip, []) if now - t < window]
        if len(h) >= limit:
            _hits[ip] = h
            return False
        h.append(now); _hits[ip] = h
    return True


def _read_jsonl(f: Path) -> list[dict]:
    out = []
    if f.exists():
        for line in f.read_text().splitlines():
            try: out.append(json.loads(line))
            except Exception: pass  # noqa: BLE001
    return out


def holder_message(eth: str) -> str:
    nonce = secrets.token_hex(8)
    with _lock:
        _nonces[eth.lower()] = (nonce, time.time())
    return (f"Nonco Autopilot: confirmo que soy dueño de esta billetera para el beneficio de holder.\n"
            f"Billetera: {eth.lower()}\nCódigo: {nonce}")


def verify_holder(eth: str, signature: str, message: str) -> dict:
    eth = eth.lower()
    with _lock:
        n = _nonces.get(eth)
    if not n or n[0] not in message or time.time() - n[1] > 1800:
        return {"firma": False, "motivo": "el código venció; volvé a firmar"}
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
        rec = Account.recover_message(encode_defunct(text=message), signature=signature).lower()
    except Exception as e:  # noqa: BLE001
        return {"firma": False, "motivo": f"firma inválida ({type(e).__name__})"}
    if rec != eth:
        return {"firma": False, "motivo": "la firma no corresponde a esa billetera"}
    out = {"firma": True, "patos": None, "estado": "a verificar"}
    if NONCO_CONTRACTS:
        total = 0
        for c in NONCO_CONTRACTS:
            data = "0x70a08231" + eth[2:].rjust(64, "0")  # balanceOf(address)
            try:
                r = requests.post(ETH_RPC, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                                 "params": [{"to": c, "data": data}, "latest"]}, timeout=10).json()
                total += int(r.get("result", "0x0"), 16)
            except Exception:  # noqa: BLE001
                return out
        out.update({"patos": total, "estado": "holder" if total > 0 else "sin patos"})
    return out


def publico() -> dict:
    try:
        d = json.load(open(STATE / "desk_summary.json"))
    except Exception:  # noqa: BLE001
        try: d = json.load(open("/var/www/fomo/desk.json"))
        except Exception: d = {}  # noqa: BLE001
    closed = d.get("closed") or []
    return {"desde": d.get("start_ts"), "inicio_usd": d.get("start_usd"), "patrimonio_usd": d.get("equity_usd"),
            "multiplo": d.get("mult"), "operaciones_cerradas": d.get("n_closed", len(closed)), "ganadas": d.get("wins"),
            "posiciones": [{"token": p.get("symbol"), "multiplo": p.get("mult"), "tesis": p.get("thesis")} for p in d.get("positions") or []],
            "ultimas": [{"token": c.get("symbol"), "resultado": c.get("ret"), "motivo": c.get("why")} for c in closed[:8]],
            "actualizado": d.get("now")}


def _sol_balance(pub: str) -> float | None:
    try:
        r = requests.post(SOL_RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pub]}, timeout=8).json()
        return r["result"]["value"] / 1e9
    except Exception:  # noqa: BLE001
        return None


def admin_resumen() -> dict:
    apps = _read_jsonl(APLIC)
    try: wallets = json.load(open(STATE / "plan_wallets.json"))
    except Exception: wallets = {}  # noqa: BLE001
    hoy = time.time() - 86400
    por_plan: dict[str, dict] = {}
    for a in apps:
        k = a.get("plan") or "sin elegir"
        x = por_plan.setdefault(k, {"aplicaciones": 0, "monto_usd": 0})
        x["aplicaciones"] += 1; x["monto_usd"] += a.get("monto_usd") or 0
    return {"aplicaciones": len(apps), "ultimas_24h": sum(1 for a in apps if a.get("ts", 0) >= hoy),
            "holders": sum(1 for a in apps if (a.get("holder") or {}).get("estado") == "holder"),
            "holders_a_verificar": sum(1 for a in apps if (a.get("holder") or {}).get("estado") == "a verificar"),
            "monto_total_usd": sum(a.get("monto_usd") or 0 for a in apps), "por_plan": por_plan,
            "billeteras_planes": {k: {"direccion": v, "sol": _sol_balance(v)} for k, v in wallets.items()},
            "usuarios_activos": 0, "capital_bajo_bot_usd": 0, "comisiones_usd": 0,
            "detalle": apps[::-1][:300], "fees": FEES, "contratos_holder": NONCO_CONTRACTS}


def aplicar(body: dict, ip: str) -> tuple[int, dict]:
    def s(k, n=120): return str(body.get(k) or "").strip()[:n]
    nombre, tg, email = s("nombre", 80), s("telegram", 40), s("email", 120)
    if not nombre or not (tg or email):
        return 400, {"error": "Completá tu nombre y un contacto (Telegram o email)."}
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return 400, {"error": "El email no parece válido."}
    plan = s("plan", 20)
    if plan and plan not in PLANS:
        return 400, {"error": "Elegí un plan de la lista."}
    try:
        monto = float(body.get("monto_usd") or 0); objetivo = float(body.get("objetivo") or 0)
        dias = int(body.get("dias") or 0); freno = float(body.get("freno_pct") or 0)
    except (TypeError, ValueError):
        return 400, {"error": "Revisá los números del monto, objetivo, plazo y freno."}
    if not (20 <= monto <= 100000):
        return 400, {"error": "El monto tiene que estar entre US$20 y US$100.000."}
    sol = s("billetera_solana", 44)
    if sol and not B58.match(sol):
        return 400, {"error": "La billetera de Solana no tiene un formato válido."}
    if not body.get("acepta_riesgos"):
        return 400, {"error": "Para aplicar tenés que aceptar los riesgos."}
    holder = None
    eth = s("eth", 42)
    if eth:
        if not ETH.match(eth):
            return 400, {"error": "La billetera de Ethereum no tiene un formato válido."}
        holder = verify_holder(eth, s("eth_firma", 200), str(body.get("eth_mensaje") or "")[:400])
        if not holder.get("firma"):
            return 400, {"error": f"No pudimos verificar el pato: {holder.get('motivo')}."}
        holder["eth"] = eth.lower()
        if any((a.get("holder") or {}).get("eth") == eth.lower() for a in _read_jsonl(APLIC)):
            return 409, {"error": "Esa billetera de Ethereum ya está asociada a otra aplicación."}
    row = {"ts": time.time(), "id": secrets.token_hex(5), "nombre": nombre, "telegram": tg.lstrip("@"), "email": email,
           "monto_usd": round(monto, 2), "objetivo": objetivo, "dias": dias, "plan": plan, "freno_pct": freno,
           "al_llegar": s("al_llegar", 20), "billetera_solana": sol, "holder": holder,
           "tipo": "holder" if holder and holder.get("estado") in ("holder", "a verificar") else "externo",
           "estado": "en lista", "ip": ip}
    with _lock, open(APLIC, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    pos = len(_read_jsonl(APLIC))
    return 200, {"ok": True, "id": row["id"], "puesto": pos, "tipo": row["tipo"]}


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _ip(self) -> str:
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/semaforo":
                return self._send(200, semaforo(float(q.get("objetivo", 2)), int(q.get("dias", 30))))
            if u.path == "/api/publico":
                return self._send(200, publico())
            if u.path == "/api/config":
                return self._send(200, {"fees": FEES, "planes": {k: {"nombre": v["nombre"], "mercados": v["mercados"]} for k, v in PLANS.items()}})
            if u.path == "/api/holder/mensaje":
                eth = q.get("eth", "")
                if not ETH.match(eth):
                    return self._send(400, {"error": "billetera de Ethereum inválida"})
                return self._send(200, {"mensaje": holder_message(eth)})
            if u.path == "/api/admin/resumen":
                return self._send(200, admin_resumen())
        except (TypeError, ValueError):
            return self._send(400, {"error": "parámetros inválidos"})
        self._send(404, {"error": "no existe"})

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/api/aplicar":
            return self._send(404, {"error": "no existe"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20000:
            return self._send(413, {"error": "demasiado grande"})
        if not _rate_ok(self._ip()):
            return self._send(429, {"error": "Demasiados intentos. Probá de nuevo en una hora."})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            return self._send(400, {"error": "datos inválidos"})
        code, out = aplicar(body, self._ip())
        self._send(code, out)

    def log_message(self, fmt, *args):  # silenciar
        pass


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
