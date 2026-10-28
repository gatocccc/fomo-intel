"""API de Lloyd's Tavern (ex Nonco Autopilot) (landing pública, cuentas de usuario y panel de administración).

Escucha en 127.0.0.1:8770, detrás de nginx (app.nonconformistducks.com). Todo lo que ve el usuario está en inglés.
Cuentas: email + contraseña (scrypt), sesión en cookie HttpOnly. Base: state/app/app.db (SQLite).

  GET  /api/semaforo?objetivo=2&dias=30    chances por plan
  GET  /api/publico                         historial en vivo de la mesa
  GET  /api/config                          comisiones y planes
  POST /api/signup  {email,password,name}   crea la cuenta e inicia sesión
  POST /api/login   {email,password}
  POST /api/logout
  GET  /api/me                              cuenta + su configuración
  POST /api/me/settings                     monto, objetivo, plazo, plan, freno, al llegar, billetera
  GET  /api/holder/message?eth=0x..         mensaje para firmar (requiere sesión)
  POST /api/holder/verify {eth,signature,message}
  GET  /api/admin/resumen | /api/admin/claves, POST /api/admin/claves   (basic auth en nginx)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from fomo_intel.app.semaforo import PLANS, semaforo

STATE = Path(os.getenv("FOMO_STATE_DIR", "state"))
APP = STATE / "app"
APP.mkdir(parents=True, exist_ok=True)
DB = APP / "app.db"
PORT = int(os.getenv("APP_PORT", "8770"))
ETH_RPC = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
FEES = {"trade_pct_holder": float(os.getenv("FEE_TRADE_HOLDER_PCT", "1")), "trade_pct_external": float(os.getenv("FEE_TRADE_EXTERNAL_PCT", "2")),
        "success_pct_external": float(os.getenv("FEE_SUCCESS_PCT", "10"))}
SOL_RPC = os.getenv("SOLANA_RPC_URL") or f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY', '')}"
SESSION_DAYS = 30
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
ETH = re.compile(r"^0x[0-9a-fA-F]{40}$")

_lock = threading.Lock()
_nonces: dict[str, tuple[str, float]] = {}
_hits: dict[str, list[float]] = {}


def nonco_contracts() -> list[str]:
    return [c.strip().lower() for c in os.getenv("NONCO_CONTRACTS", "").split(",") if c.strip()]


# ---------- base de datos ----------
def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, pw TEXT NOT NULL, created REAL,
          amount_usd REAL, goal REAL, days INTEGER, plan TEXT, stop_pct REAL, at_goal TEXT, sol_wallet TEXT,
          eth TEXT UNIQUE, ducks INTEGER, holder_status TEXT, status TEXT DEFAULT 'waitlist', bot_wallet TEXT, last_login REAL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
        """)
    os.chmod(DB, 0o600)


def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return salt.hex() + ":" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":")
        return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex(), h)
    except Exception:  # noqa: BLE001
        return False


def new_session(uid: int) -> str:
    tok = secrets.token_urlsafe(32)
    with db() as c:
        c.execute("INSERT INTO sessions VALUES (?,?,?)", (tok, uid, time.time() + SESSION_DAYS * 86400))
        c.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), uid))
    return tok


def user_by_token(tok: str | None) -> sqlite3.Row | None:
    if not tok:
        return None
    with db() as c:
        return c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?",
                         (tok, time.time())).fetchone()


def public_user(u: sqlite3.Row) -> dict:
    d = dict(u); d.pop("pw", None)
    with db() as c:
        d["position"] = c.execute("SELECT COUNT(*) FROM users WHERE created<=?", (u["created"],)).fetchone()[0]
    d["type"] = "holder" if u["holder_status"] in ("holder", "pending") else "external"
    return d


def _rate_ok(key: str, limit: int, window: int = 3600) -> bool:
    now = time.time()
    with _lock:
        h = [t for t in _hits.get(key, []) if now - t < window]
        ok = len(h) < limit
        if ok:
            h.append(now)
        _hits[key] = h
    return ok


# ---------- cuentas ----------
def signup(b: dict) -> tuple[int, dict, str | None]:
    email = str(b.get("email") or "").strip().lower()[:254]
    pw = str(b.get("password") or "")
    name = str(b.get("name") or "").strip()[:80]
    if not EMAIL.match(email):
        return 400, {"error": "Enter a valid email."}, None
    if len(pw) < 10:
        return 400, {"error": "Use a password of at least 10 characters."}, None
    if not b.get("accept_risk"):
        return 400, {"error": "You need to accept the risks to create an account."}, None
    try:
        with db() as c:
            cur = c.execute("INSERT INTO users (email,name,pw,created,status) VALUES (?,?,?,?, 'waitlist')",
                            (email, name, hash_pw(pw), time.time()))
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        return 409, {"error": "That email already has an account. Log in instead."}, None
    return 200, {"ok": True}, new_session(uid)


def login(b: dict) -> tuple[int, dict, str | None]:
    email = str(b.get("email") or "").strip().lower()
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not u or not check_pw(str(b.get("password") or ""), u["pw"]):
        return 401, {"error": "Wrong email or password."}, None
    return 200, {"ok": True}, new_session(u["id"])


def save_settings(u: sqlite3.Row, b: dict) -> tuple[int, dict]:
    try:
        amount = float(b.get("amount_usd") or 0); goal = float(b.get("goal") or 0)
        days = int(b.get("days") or 0); stop = float(b.get("stop_pct") or 0)
    except (TypeError, ValueError):
        return 400, {"error": "Check the numbers."}
    plan = str(b.get("plan") or "")
    at_goal = str(b.get("at_goal") or "lock")
    sol = str(b.get("sol_wallet") or "").strip()
    if not (20 <= amount <= 100000): return 400, {"error": "Amount must be between $20 and $100,000."}
    if not (1.01 <= goal <= 100): return 400, {"error": "Goal must be between x1.01 and x100."}
    if not (7 <= days <= 120): return 400, {"error": "Timeframe must be between 7 and 120 days."}
    if not (5 <= stop <= 95): return 400, {"error": "Your stop must be between 5% and 95%."}
    if plan and plan not in PLANS: return 400, {"error": "Pick a plan from the list."}
    if at_goal not in ("lock", "lock_profit", "continue"): return 400, {"error": "Pick what happens at your goal."}
    if sol and not B58.match(sol): return 400, {"error": "That Solana address doesn't look right."}
    with db() as c:
        c.execute("UPDATE users SET amount_usd=?,goal=?,days=?,plan=?,stop_pct=?,at_goal=?,sol_wallet=? WHERE id=?",
                  (amount, goal, days, plan or None, stop, at_goal, sol or None, u["id"]))
        u2 = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    return 200, {"ok": True, "user": public_user(u2)}


# ---------- holders (firma de Ethereum) ----------
def holder_message(uid: int, eth: str) -> str:
    nonce = secrets.token_hex(8)
    with _lock:
        _nonces[f"{uid}:{eth.lower()}"] = (nonce, time.time())
    return f"Lloyd's Tavern: I own this wallet and want the holder benefit.\nWallet: {eth.lower()}\nCode: {nonce}"


def count_ducks(eth: str) -> int | None:
    cs = nonco_contracts()
    if not cs:
        return None
    total = 0
    for c in cs:
        data = "0x70a08231" + eth[2:].lower().rjust(64, "0")  # balanceOf(address)
        try:
            r = requests.post(ETH_RPC, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                             "params": [{"to": c, "data": data}, "latest"]}, timeout=10).json()
            total += int(r.get("result", "0x0"), 16)
        except Exception:  # noqa: BLE001
            return None
    return total


def verify_holder(u: sqlite3.Row, b: dict) -> tuple[int, dict]:
    eth = str(b.get("eth") or "").lower(); sig = str(b.get("signature") or ""); msg = str(b.get("message") or "")[:400]
    if not ETH.match(eth):
        return 400, {"error": "Invalid Ethereum address."}
    with _lock:
        n = _nonces.get(f"{u['id']}:{eth}")
    if not n or n[0] not in msg or time.time() - n[1] > 1800:
        return 400, {"error": "The code expired. Sign again."}
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
        rec = Account.recover_message(encode_defunct(text=msg), signature=sig).lower()
    except Exception:  # noqa: BLE001
        return 400, {"error": "Invalid signature."}
    if rec != eth:
        return 400, {"error": "The signature doesn't match that wallet."}
    ducks = count_ducks(eth)
    status = "pending" if ducks is None else ("holder" if ducks > 0 else "none")
    try:
        with db() as c:
            c.execute("UPDATE users SET eth=?, ducks=?, holder_status=? WHERE id=?", (eth, ducks, status, u["id"]))
            u2 = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    except sqlite3.IntegrityError:
        return 409, {"error": "That wallet is already linked to another account. One person, one account, however many ducks you hold."}
    return 200, {"ok": True, "user": public_user(u2)}


def recheck_pending() -> None:
    """Cuando se cargan los contratos, revisa los holders que quedaron 'pending'."""
    if not nonco_contracts():
        return
    with db() as c:
        rows = c.execute("SELECT id, eth FROM users WHERE holder_status='pending' AND eth IS NOT NULL").fetchall()
    for r in rows:
        ducks = count_ducks(r["eth"])
        if ducks is not None:
            with db() as c:
                c.execute("UPDATE users SET ducks=?, holder_status=? WHERE id=?", (ducks, "holder" if ducks > 0 else "none", r["id"]))


# ---------- datos públicos y admin ----------
def publico() -> dict:
    try:
        d = json.load(open(STATE / "desk_summary.json"))
    except Exception:  # noqa: BLE001
        try: d = json.load(open("/var/www/fomo/desk.json"))
        except Exception: d = {}  # noqa: BLE001
    closed = d.get("closed") or []
    return {"since": d.get("start_ts"), "start_usd": d.get("start_usd"), "equity_usd": d.get("equity_usd"),
            "multiple": d.get("mult"), "closed_trades": d.get("n_closed", len(closed)), "wins": d.get("wins"),
            "positions": [{"token": p.get("symbol"), "multiple": p.get("mult")} for p in d.get("positions") or []],
            "recent": [{"token": c.get("symbol"), "result": c.get("ret")} for c in closed[:8]],
            "updated": d.get("now")}


PLAN_KEYS = ("agresivo", "equilibrado", "tradicional")


def _summary(path: Path) -> dict | None:
    try:
        return json.load(open(path))
    except Exception:  # noqa: BLE001
        return None


def wallet_view(d: dict, full: bool = False) -> dict:
    """Vista de una billetera que opera (plan de la casa o, más adelante, la de un usuario)."""
    start, eq = d.get("start_usd"), d.get("equity_usd")
    closed = d.get("closed") or []
    out = {"wallet": d.get("wallet"), "started": d.get("started", True) and bool(d.get("start_ts")), "since": d.get("start_ts"),
           "start_usd": start, "equity_usd": eq, "pnl_usd": round(eq - start, 2) if start and eq is not None else None,
           "pnl_pct": round(eq / start - 1, 4) if start and eq else None, "cash_sol": d.get("cash_sol"),
           "open": len(d.get("positions") or []), "closed": d.get("n_closed", len(closed)), "wins": d.get("wins"),
           "realized_usd": d.get("realized_usd"), "halted": d.get("halt"), "updated": d.get("now"),
           "last_trade": (d.get("trades") or [{}])[0].get("ts") if d.get("trades") else None,
           "positions": [{"token": x.get("symbol"), "mint": x.get("mint"), "multiple": x.get("mult"), "value_usd": x.get("value_usd"),
                          "stop": x.get("stop"), "thesis": x.get("thesis")} for x in d.get("positions") or []]}
    if full:
        out["equity"] = (d.get("equity") or [])[-400:]
        out["closed_list"] = [{"token": c.get("symbol"), "result": c.get("ret"), "pnl_usd": c.get("pnl_usd"), "why": c.get("why"), "ts": c.get("ts")} for c in closed[:30]]
        out["journal"] = [{"ts": j.get("ts"), "title": j.get("title"), "text": j.get("text"), "kind": j.get("kind")} for j in (d.get("journal") or [])[:40]]
    return out


def plans_public() -> dict:
    out = {}
    for k in PLAN_KEYS:
        d = _summary(STATE / f"plan_{k}_summary.json") or {}
        out[k] = {"name": PLANS[k]["nombre"], "markets": PLANS[k]["mercados"], **wallet_view(d, full=True)}
    return {"plans": out}


def trading_wallets() -> list[dict]:
    rows = []
    for k in PLAN_KEYS:
        d = _summary(STATE / f"plan_{k}_summary.json")
        if d:
            rows.append({"owner": "Tavern house plan", "email": None, "plan": k, **wallet_view(d)})
    with db() as c:
        users = c.execute("SELECT id, email, name, plan, bot_wallet, holder_status FROM users WHERE bot_wallet IS NOT NULL").fetchall()
    for u in users:
        d = _summary(STATE / "users" / f"{u['id']}_summary.json") or {"wallet": u["bot_wallet"]}
        rows.append({"owner": u["name"] or u["email"], "email": u["email"], "plan": u["plan"], "holder": u["holder_status"] == "holder", **wallet_view(d)})
    return rows


def _sol_balance(pub: str) -> float | None:
    try:
        r = requests.post(SOL_RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pub]}, timeout=8).json()
        return r["result"]["value"] / 1e9
    except Exception:  # noqa: BLE001
        return None


def admin_resumen() -> dict:
    with db() as c:
        users = [dict(r) for r in c.execute("SELECT * FROM users ORDER BY created DESC").fetchall()]
    for u in users:
        u.pop("pw", None)
    try: wallets = json.load(open(STATE / "plan_wallets.json"))
    except Exception: wallets = {}  # noqa: BLE001
    tw = trading_wallets()
    day = time.time() - 86400
    by_plan: dict[str, dict] = {}
    for u in users:
        x = by_plan.setdefault(u.get("plan") or "not chosen", {"users": 0, "amount_usd": 0})
        x["users"] += 1; x["amount_usd"] += u.get("amount_usd") or 0
    return {"users": len(users), "new_24h": sum(1 for u in users if (u.get("created") or 0) >= day),
            "logins_24h": sum(1 for u in users if (u.get("last_login") or 0) >= day),
            "holders": sum(1 for u in users if u.get("holder_status") == "holder"),
            "holders_pending": sum(1 for u in users if u.get("holder_status") == "pending"),
            "pledged_usd": sum(u.get("amount_usd") or 0 for u in users), "by_plan": by_plan,
            "active_wallets": sum(1 for w in tw if w.get("started")), "capital_under_bot_usd": round(sum(w.get("equity_usd") or 0 for w in tw if w.get("started")), 2),
            "pnl_usd": round(sum(w.get("pnl_usd") or 0 for w in tw if w.get("started")), 2), "fees_usd": 0,
            "plan_wallets": {k: {"address": v, "sol": _sol_balance(v)} for k, v in wallets.items()},
            "detail": users[:500], "fees": FEES, "holder_contracts": nonco_contracts()}


CLAVES = {"JUPITER_API_KEY": "Jupiter API key", "TURNKEY_ORG_ID": "Turnkey organization ID",
          "TURNKEY_API_USER_ID": "Turnkey API user ID", "NONCO_CONTRACTS": "Nonco Genesis contract addresses (comma separated)"}
ENV = Path(os.getenv("FOMO_ENV_FILE", ".env"))


def claves_estado() -> dict:
    txt = ENV.read_text() if ENV.exists() else ""
    have = {l.split("=", 1)[0].strip() for l in txt.splitlines() if "=" in l and l.split("=", 1)[1].strip()}
    return {"claves": [{"nombre": k, "descripcion": v, "cargada": k in have} for k, v in CLAVES.items()]}


def claves_guardar(b: dict) -> tuple[int, dict]:
    k = str(b.get("nombre") or ""); v = str(b.get("valor") or "").strip()
    if k not in CLAVES or not v or len(v) > 500 or "\n" in v or "\r" in v:
        return 400, {"error": "Invalid key or value."}
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [l for l in lines if not l.startswith(k + "=")] + [f"{k}={v}"]
    tmp = ENV.with_suffix(".tmp"); tmp.write_text("\n".join(lines) + "\n"); os.chmod(tmp, 0o600); tmp.replace(ENV)
    os.environ[k] = v
    if k == "NONCO_CONTRACTS":
        threading.Thread(target=recheck_pending, daemon=True).start()
    return 200, {"ok": True, **claves_estado()}


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict, cookie: str | None = None, clear: bool = False) -> None:
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", f"np_session={cookie}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; Secure; SameSite=Lax")
        if clear:
            self.send_header("Set-Cookie", "np_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _ip(self) -> str:
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def _token(self) -> str | None:
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return c["np_session"].value if "np_session" in c else None

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/semaforo":
                return self._send(200, semaforo(float(q.get("objetivo", 2)), int(q.get("dias", 30))))
            if u.path == "/api/publico":
                return self._send(200, publico())
            if u.path == "/api/config":
                return self._send(200, {"fees": FEES, "plans": {k: {"name": v["nombre"], "markets": v["mercados"]} for k, v in PLANS.items()}})
            if u.path == "/api/me":
                usr = user_by_token(self._token())
                return self._send(200, {"user": public_user(usr)}) if usr else self._send(401, {"error": "Not logged in."})
            if u.path == "/api/holder/message":
                usr = user_by_token(self._token())
                if not usr: return self._send(401, {"error": "Not logged in."})
                eth = q.get("eth", "")
                if not ETH.match(eth): return self._send(400, {"error": "Invalid Ethereum address."})
                return self._send(200, {"message": holder_message(usr["id"], eth)})
            if u.path == "/api/plans":
                return self._send(200, plans_public())
            if u.path == "/api/admin/wallets":
                return self._send(200, {"wallets": trading_wallets()})
            if u.path == "/api/admin/wallet":
                k = q.get("plan", "")
                d = _summary(STATE / f"plan_{k}_summary.json") if k in PLAN_KEYS else None
                return self._send(200, wallet_view(d, full=True)) if d else self._send(404, {"error": "Not found."})
            if u.path == "/api/admin/resumen":
                return self._send(200, admin_resumen())
            if u.path == "/api/admin/claves":
                return self._send(200, claves_estado())
        except (TypeError, ValueError):
            return self._send(400, {"error": "Invalid parameters."})
        self._send(404, {"error": "Not found."})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20000:
            return self._send(413, {"error": "Too large."})
        try:
            b = json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            return self._send(400, {"error": "Invalid data."})
        ip = self._ip()
        if path == "/api/signup":
            if not _rate_ok("su:" + ip, 5): return self._send(429, {"error": "Too many attempts. Try again in an hour."})
            code, out, tok = signup(b); return self._send(code, out, cookie=tok)
        if path == "/api/login":
            if not _rate_ok("li:" + ip, 20) or not _rate_ok("le:" + str(b.get("email", "")).lower(), 10):
                return self._send(429, {"error": "Too many attempts. Try again in an hour."})
            code, out, tok = login(b); return self._send(code, out, cookie=tok)
        if path == "/api/logout":
            tok = self._token()
            if tok:
                with db() as c: c.execute("DELETE FROM sessions WHERE token=?", (tok,))
            return self._send(200, {"ok": True}, clear=True)
        if path == "/api/admin/claves":
            code, out = claves_guardar(b); return self._send(code, out)
        usr = user_by_token(self._token())
        if not usr:
            return self._send(401, {"error": "Not logged in."})
        if path == "/api/me/settings":
            code, out = save_settings(usr, b); return self._send(code, out)
        if path == "/api/holder/verify":
            code, out = verify_holder(usr, b); return self._send(code, out)
        self._send(404, {"error": "Not found."})

    def log_message(self, fmt, *args):  # silenciar
        pass


def main() -> None:
    init_db()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
