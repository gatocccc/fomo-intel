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
  GET  /api/ideas | POST /api/ideas {title,idea,why,name,contact} | POST /api/ideas/vote {id}   ideas de la comunidad para el lab
  GET  /api/admin/resumen | /api/admin/claves, POST /api/admin/claves   (basic auth en nginx)
  GET  /api/admin/ideas, POST /api/admin/ideas {id,status,reply,ledger_name}
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

from fomo_intel.app.book import PROFIT_RULES, RISK_LEVELS, book_view, expect, lab_public, research
from fomo_intel.app.semaforo import PLANS, semaforo

STATE = Path(os.getenv("FOMO_STATE_DIR", "state"))
APP = STATE / "app"
APP.mkdir(parents=True, exist_ok=True)
DB = APP / "app.db"
PORT = int(os.getenv("APP_PORT", "8770"))
ETH_RPC = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
# Pricing (decisión de Gastón, 29/10/2026): 1% embebido en cada compra/venta de tokens para todos (no en los pases a USDC/SOL);
# holders nada más; externos 1,5% por operación con tokens y además 15% de la ganancia neta mensual con marca de agua; mínimo US$300; sin cuota de ingreso.
FEES = {"trade_pct_holder": float(os.getenv("FEE_TRADE_HOLDER_PCT", "1")), "trade_pct_external": float(os.getenv("FEE_TRADE_EXTERNAL_PCT", "1.5")),
        "success_pct_external": float(os.getenv("FEE_SUCCESS_PCT", "15")), "success_pct_holder": 0.0,
        "trade_fee_on": "token trades only", "success_basis": "net monthly profit above the previous high (high-water mark)",
        "min_deposit_usd": float(os.getenv("MIN_DEPOSIT_USD", "300"))}
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
        CREATE TABLE IF NOT EXISTS ideas (
          id INTEGER PRIMARY KEY, created REAL, title TEXT, idea TEXT, why TEXT, name TEXT, contact TEXT, user_id INTEGER,
          ip_h TEXT, status TEXT DEFAULT 'new', reply TEXT, ledger_name TEXT, reviewed REAL);
        CREATE TABLE IF NOT EXISTS idea_votes (idea_id INTEGER, voter TEXT, ts REAL, PRIMARY KEY (idea_id, voter));
        """)
        for col, typ in (("risk_pct", "INTEGER"), ("profit_rule", "TEXT"), ("profit_mult", "REAL"), ("close_requested", "REAL")):
            try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
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
    d["stool"] = stool_view(u["id"])
    return d


def stool_view(uid: int) -> dict | None:
    """La billetera del usuario, como la publica el motor de seguidores (fomo_intel/desk/mirror.py)."""
    s = _summary(STATE / "users" / f"{uid}_summary.json")
    if not s:
        return None
    keep = ("wallet", "type", "fee_pct", "started", "since", "halt", "stopped", "stray_usd", "equity_usd", "deposited_usd", "withdrawn_usd", "pnl_usd", "pnl_pct", "fees_usd",
            "cash_usd", "cash_sol", "min_sol", "sol_usd", "now")
    out = {k: s.get(k) for k in keep}
    out["positions"] = s.get("positions") or []
    out["equity"] = (s.get("equity") or [])[-400:]
    out["pct_series"] = (s.get("pct_series") or [])[-400:]
    out["closed_list"] = [{"ts": c.get("ts"), "token": c.get("symbol"), "sleeve": c.get("sleeve"), "result": c.get("ret"), "pnl_usd": c.get("pnl_usd"), "why": c.get("why"), "hold_h": c.get("hold_h")} for c in (s.get("closed") or [])[:30]]
    out["journal"] = [{"ts": j.get("ts"), "title": j.get("title"), "text": j.get("text"), "kind": j.get("kind")} for j in (s.get("journal") or [])[:40]]
    return out


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
    if "risk_pct" in b or "profit_rule" in b:
        return save_dials(u, b)
    try:
        amount = float(b.get("amount_usd") or 0); goal = float(b.get("goal") or 0)
        days = int(b.get("days") or 0); stop = float(b.get("stop_pct") or 0)
    except (TypeError, ValueError):
        return 400, {"error": "Check the numbers."}
    plan = str(b.get("plan") or "")
    at_goal = str(b.get("at_goal") or "lock")
    sol = str(b.get("sol_wallet") or "").strip()
    if not (FEES["min_deposit_usd"] <= amount <= 100000): return 400, {"error": f"Amount must be between ${FEES['min_deposit_usd']:.0f} and $100,000."}
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


def save_dials(u: sqlite3.Row, b: dict) -> tuple[int, dict]:
    """Los tres diales del libro único: cuánto, cuánto riesgo, qué pasa con las ganancias."""
    try:
        amount = float(b.get("amount_usd") or 0); risk = int(b.get("risk_pct") or 0)
        mult = float(b.get("profit_mult") or 0) if b.get("profit_mult") not in (None, "") else None
    except (TypeError, ValueError):
        return 400, {"error": "Check the numbers."}
    rule = str(b.get("profit_rule") or "run"); sol = str(b.get("sol_wallet") or "").strip()
    if not (FEES["min_deposit_usd"] <= amount <= 100000): return 400, {"error": f"Amount must be between ${FEES['min_deposit_usd']:.0f} and $100,000."}
    if risk not in {r["pct"] for r in RISK_LEVELS}: return 400, {"error": "Pick a risk level."}
    if rule not in {r["key"] for r in PROFIT_RULES}: return 400, {"error": "Pick what happens with profits."}
    if rule == "lock" and (mult is None or not (1.2 <= mult <= 10)): return 400, {"error": "Pick a multiple between x1.2 and x10 to lock in at."}
    if rule == "sweep" and not sol: return 400, {"error": "Monthly sweeps need your Solana wallet."}
    if sol and not B58.match(sol): return 400, {"error": "That Solana address doesn't look right."}
    with db() as c:
        c.execute("UPDATE users SET amount_usd=?,risk_pct=?,profit_rule=?,profit_mult=?,sol_wallet=?,stop_pct=? WHERE id=?",
                  (amount, risk, rule, mult if rule == "lock" else None, sol or None, risk, u["id"]))
        u2 = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    return 200, {"ok": True, "user": public_user(u2)}


def close_all(u: sqlite3.Row) -> tuple[int, dict]:
    if not u["bot_wallet"]:
        return 409, {"error": "You do not have a stool yet, so there is nothing to close. Your seat is still on the waitlist."}
    with db() as c:
        c.execute("UPDATE users SET close_requested=?, status='closing' WHERE id=?", (time.time(), u["id"]))
    (STATE / "users").mkdir(parents=True, exist_ok=True)
    (STATE / "users" / f"{u['id']}_CLOSE").write_text(str(time.time()))
    return 200, {"ok": True}


def resume(u: sqlite3.Row) -> tuple[int, dict]:
    """Vuelve a poner a Lloyd a trabajar en una billetera parada (Stop o piso). El motor de seguidores la rearranca con lo que hay."""
    if not u["bot_wallet"]:
        return 409, {"error": "You do not have a stool yet."}
    with db() as c:
        c.execute("UPDATE users SET status='seated', close_requested=NULL WHERE id=?", (u["id"],))
    (STATE / "users").mkdir(parents=True, exist_ok=True)
    (STATE / "users" / f"{u['id']}_RESUME").write_text(str(time.time()))
    return 200, {"ok": True}


def withdraw(u: sqlite3.Row) -> tuple[int, dict]:
    if not u["bot_wallet"]:
        return 409, {"error": "You do not have a stool yet."}
    if not u["sol_wallet"]:
        return 400, {"error": "Save the Solana wallet you want the money sent to first (in your dials)."}
    (STATE / "users").mkdir(parents=True, exist_ok=True)
    (STATE / "users" / f"{u['id']}_WITHDRAW").write_text(str(time.time()))
    return 200, {"ok": True}


def tip_lab(u: sqlite3.Row, b: dict) -> tuple[int, dict]:
    """Propina al laboratorio desde la billetera del usuario: el motor de seguidores la transfiere a la billetera del lab."""
    if not u["bot_wallet"]:
        return 409, {"error": "You do not have a stool yet."}
    try: sol = float(b.get("sol") or 0)
    except (TypeError, ValueError): return 400, {"error": "How much?"}
    if not (0.01 <= sol <= 5): return 400, {"error": "Between 0.01 and 5 SOL."}
    (STATE / "users").mkdir(parents=True, exist_ok=True)
    (STATE / "users" / f"{u['id']}_TIP").write_text(json.dumps({"sol": sol, "ts": time.time()}))
    return 200, {"ok": True}


def admin_seat(b: dict) -> tuple[int, dict]:
    """Da asiento (status='seated'): el motor de seguidores le crea la billetera en su próximo ciclo. 'unseat' lo saca del motor (no toca la plata)."""
    try: uid = int(b.get("id"))
    except (TypeError, ValueError): return 400, {"error": "Which user?"}
    action = b.get("action") or "seat"
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row: return 404, {"error": "No such user."}
        if action == "seat":
            c.execute("UPDATE users SET status='seated' WHERE id=?", (uid,))
        elif action == "unseat":
            c.execute("UPDATE users SET status='waitlist' WHERE id=?", (uid,))
        elif action == "holder":      # marcado a mano (p. ej. patos de las colecciones viejas mientras Genesis no está minteada)
            c.execute("UPDATE users SET holder_status='holder', ducks=COALESCE(NULLIF(ducks,0),1) WHERE id=?", (uid,))
        elif action == "standard":
            c.execute("UPDATE users SET holder_status='none', ducks=0 WHERE id=?", (uid,))
        else:
            return 400, {"error": "seat, unseat, holder or standard"}
    return 200, {"ok": True, "action": action}


# ---------- ideas de la comunidad para el laboratorio (/lab/) ----------
# Nada es público hasta que se revisa (status 'new' = solo admin). El contacto nunca sale del admin.
# Estados: new → queued (entra a la cola del lab) | testing | done (probada; el resultado está en la bitácora)
#          | merged (ya estaba cubierta por otra prueba) | declined (con respuesta) | spam (oculta).
IDEA_STATUS = ("new", "queued", "testing", "done", "merged", "declined", "spam")
IDEA_PUBLIC = {"queued": "In the queue", "testing": "Testing now", "done": "Tested", "merged": "Already on the table", "declined": "Not for now"}
IDEAS_INBOX = STATE / "research" / "ideas_inbox.json"


def _ip_h(ip: str) -> str:
    return hashlib.sha256(("ideas:" + ip + os.getenv("IDEAS_SALT", "lloyd")).encode()).hexdigest()[:16]


def _ideas_inbox() -> None:
    """Exporta las ideas (sin contacto ni IP) para que las sesiones de investigación las lean."""
    with db() as c:
        rows = c.execute("SELECT id,created,title,idea,why,name,status,reply,ledger_name,"
                         "(SELECT COUNT(*) FROM idea_votes v WHERE v.idea_id=ideas.id) AS votes FROM ideas WHERE status!='spam' ORDER BY id").fetchall()
    IDEAS_INBOX.parent.mkdir(parents=True, exist_ok=True)
    tmp = IDEAS_INBOX.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": time.time(), "ideas": [dict(r) for r in rows]}, ensure_ascii=False, indent=1))
    tmp.replace(IDEAS_INBOX)


def idea_submit(b: dict, ip: str, usr: sqlite3.Row | None) -> tuple[int, dict]:
    if str(b.get("website") or "").strip():          # trampa para bots: campo oculto
        return 200, {"ok": True}
    title = " ".join(str(b.get("title") or "").split())[:90]
    idea = str(b.get("idea") or "").strip()[:1500]
    why = str(b.get("why") or "").strip()[:600]
    name = " ".join(str(b.get("name") or "").split())[:40]
    contact = str(b.get("contact") or "").strip()[:120]
    if len(title) < 6:
        return 400, {"error": "Give the idea a short title (at least 6 characters)."}
    if len(idea) < 30:
        return 400, {"error": "Tell Lloyd a bit more: what would he watch for, and what would he do? (30 characters or more)"}
    if re.search(r"(https?://\S+.*){4,}", idea + " " + why):
        return 400, {"error": "Too many links. Describe the idea in your own words."}
    with db() as c:
        dup = c.execute("SELECT id FROM ideas WHERE lower(title)=lower(?) AND created>?", (title, time.time() - 30 * 86400)).fetchone()
        if dup:
            return 409, {"error": "Someone already pitched an idea with that title. Give it a vote instead."}
        cur = c.execute("INSERT INTO ideas (created,title,idea,why,name,contact,user_id,ip_h,status) VALUES (?,?,?,?,?,?,?,?, 'new')",
                        (time.time(), title, idea, why, name or None, contact or None, usr["id"] if usr else None, _ip_h(ip)))
        iid = cur.lastrowid
    _ideas_inbox()
    return 200, {"ok": True, "id": iid}


def ideas_public() -> dict:
    with db() as c:
        rows = c.execute("SELECT i.id,i.created,i.title,i.idea,i.why,i.name,i.status,i.reply,i.ledger_name,i.reviewed,"
                         "(SELECT COUNT(*) FROM idea_votes v WHERE v.idea_id=i.id) AS votes FROM ideas i "
                         "WHERE i.status IN ('queued','testing','done','merged','declined') ORDER BY i.reviewed DESC LIMIT 60").fetchall()
        pending = c.execute("SELECT COUNT(*) FROM ideas WHERE status='new'").fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM ideas WHERE status!='spam'").fetchone()[0]
    order = {"testing": 0, "queued": 1, "done": 2, "merged": 3, "declined": 4}
    out = [{"id": r["id"], "date": time.strftime("%Y-%m-%d", time.gmtime(r["created"])), "title": r["title"], "idea": r["idea"], "why": r["why"],
            "by": r["name"] or "Anonymous", "status": r["status"], "status_label": IDEA_PUBLIC.get(r["status"], r["status"]),
            "reply": r["reply"], "experiment": r["ledger_name"], "votes": r["votes"]} for r in rows]
    out.sort(key=lambda x: (order.get(x["status"], 9), -x["votes"]))
    return {"ideas": out, "pending": pending, "total": total, "updated": time.time()}


def idea_vote(b: dict, ip: str, usr: sqlite3.Row | None) -> tuple[int, dict]:
    try: iid = int(b.get("id"))
    except (TypeError, ValueError): return 400, {"error": "Which idea?"}
    voter = f"u{usr['id']}" if usr else "ip" + _ip_h(ip)
    with db() as c:
        row = c.execute("SELECT status FROM ideas WHERE id=?", (iid,)).fetchone()
        if not row or row["status"] not in ("queued", "testing", "merged"):
            return 404, {"error": "That idea is not open for votes."}
        c.execute("INSERT OR IGNORE INTO idea_votes VALUES (?,?,?)", (iid, voter, time.time()))
        n = c.execute("SELECT COUNT(*) FROM idea_votes WHERE idea_id=?", (iid,)).fetchone()[0]
    _ideas_inbox()
    return 200, {"ok": True, "votes": n}


def ideas_admin() -> dict:
    with db() as c:
        rows = c.execute("SELECT i.*, (SELECT COUNT(*) FROM idea_votes v WHERE v.idea_id=i.id) AS votes, u.email AS user_email "
                         "FROM ideas i LEFT JOIN users u ON u.id=i.user_id ORDER BY (i.status='new') DESC, i.id DESC LIMIT 300").fetchall()
    out = []
    for r in rows:
        d = dict(r); d.pop("ip_h", None); out.append(d)
    return {"ideas": out, "statuses": IDEA_STATUS}


def idea_review(b: dict) -> tuple[int, dict]:
    try: iid = int(b.get("id"))
    except (TypeError, ValueError): return 400, {"error": "Which idea?"}
    st = str(b.get("status") or "")
    if st not in IDEA_STATUS: return 400, {"error": "Unknown status."}
    reply = str(b.get("reply") or "").strip()[:800] or None
    ledger = str(b.get("ledger_name") or "").strip()[:120] or None
    with db() as c:
        if not c.execute("SELECT 1 FROM ideas WHERE id=?", (iid,)).fetchone(): return 404, {"error": "No such idea."}
        c.execute("UPDATE ideas SET status=?, reply=COALESCE(?,reply), ledger_name=COALESCE(?,ledger_name), reviewed=? WHERE id=?",
                  (st, reply, ledger, time.time(), iid))
    _ideas_inbox()
    return 200, {"ok": True}


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
    b = book_view(full=False)
    if b:
        return {"since": b["since"], "start_usd": b["start_usd"], "equity_usd": b["equity_usd"], "multiple": round(b["equity_usd"] / b["start_usd"], 3) if b["start_usd"] else None,
                "closed_trades": b["stats"]["closed"], "wins": b["stats"]["wins"], "positions": [{"token": p["token"], "multiple": p["multiple"]} for p in b["positions"]],
                "recent": [{"token": c["token"], "result": c["result"]} for c in book_view(full=True)["closed_list"][:8]], "updated": b["updated"]}
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
    start, eq = d.get("start_usd") if d.get("start_usd") is not None else d.get("deposited_usd"), d.get("equity_usd")
    closed = d.get("closed") or []
    # Los resúmenes de los stools (mirror.py) traen `started`/`since`; el del libro trae `start_ts`. Hasta el 30/10 acá se exigía
    # `start_ts` y todas las billeteras de usuarios figuraban "waiting for funds" con plata adentro (y no sumaban al capital bajo el bot).
    since = d.get("start_ts") or d.get("since")
    out = {"wallet": d.get("wallet"), "started": bool(d.get("started", True)) and bool(since), "since": since,
           "start_usd": start, "equity_usd": eq,
           "pnl_usd": d.get("pnl_usd") if d.get("pnl_usd") is not None else (round(eq - start, 2) if start and eq is not None else None),
           "pnl_pct": d.get("pnl_pct") if d.get("pnl_pct") is not None else (round(eq / start - 1, 4) if start and eq else None), "cash_sol": d.get("cash_sol"),
           "open": len(d.get("positions") or []), "closed": d.get("n_closed", len(closed)),
           "wins": d.get("wins") if d.get("wins") is not None else sum(1 for c in closed if (c.get("pnl_usd") or 0) > 0),
           "realized_usd": d.get("realized_usd"), "halted": d.get("halt"), "closed_out": d.get("stopped") if "stopped" in d else (d.get("closed") if isinstance(d.get("closed"), bool) else None), "updated": d.get("now"), "stray_usd": d.get("stray_usd") or 0,
           "fees_usd": d.get("fees_usd"),
           "last_trade": (d.get("trades") or [{}])[0].get("ts") if d.get("trades") else None,
           "positions": [{"token": x.get("symbol") or x.get("token"), "mint": x.get("mint"), "multiple": x.get("mult") if x.get("mult") is not None else x.get("multiple"), "value_usd": x.get("value_usd"),
                          "stop": x.get("stop"), "thesis": x.get("thesis"),
                          "chart": (f"https://dexscreener.com/solana/{x.get('mint')}" if x.get("mint") and x.get("mint") not in ("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",) else None)}
                         for x in d.get("positions") or []]}
    b = d.get("brain") or {}
    if b:
        out["brain"] = {"live": b.get("mode") == "live", "last_run": b.get("last_run"), "market": b.get("regime"),
                        "sol_24h": b.get("sol_ch24h"), "trend": b.get("trad_status")}
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
    d = _summary(STATE / "plan_lloyd_summary.json")
    if d and d.get("start_ts"):
        rows.append({"owner": "The house book", "email": None, "plan": "lloyd", "book": "lloyd", **wallet_view(d)})
    else:
        for k in PLAN_KEYS:
            d = _summary(STATE / f"plan_{k}_summary.json")
            if d:
                rows.append({"owner": "Tavern house plan", "email": None, "plan": k, **wallet_view(d)})
    with db() as c:
        users = c.execute("SELECT id, email, name, plan, bot_wallet, holder_status, risk_pct, profit_rule FROM users WHERE bot_wallet IS NOT NULL").fetchall()
    for u in users:
        d = _summary(STATE / "users" / f"{u['id']}_summary.json") or {"wallet": u["bot_wallet"]}
        rows.append({"owner": u["name"] or u["email"], "email": u["email"], "plan": u["plan"], "risk_pct": u["risk_pct"] if "risk_pct" in u.keys() else None,
                     "profit_rule": u["profit_rule"] if "profit_rule" in u.keys() else None, "holder": u["holder_status"] == "holder", **wallet_view(d)})
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
    by_plan: dict[str, dict] = {}; by_risk: dict[str, dict] = {}
    for u in users:
        x = by_plan.setdefault(u.get("plan") or "not chosen", {"users": 0, "amount_usd": 0})
        x["users"] += 1; x["amount_usd"] += u.get("amount_usd") or 0
        y = by_risk.setdefault(str(u.get("risk_pct") or "not chosen"), {"users": 0, "amount_usd": 0})
        y["users"] += 1; y["amount_usd"] += u.get("amount_usd") or 0
    return {"users": len(users), "new_24h": sum(1 for u in users if (u.get("created") or 0) >= day),
            "logins_24h": sum(1 for u in users if (u.get("last_login") or 0) >= day),
            "holders": sum(1 for u in users if u.get("holder_status") == "holder"),
            "holders_pending": sum(1 for u in users if u.get("holder_status") == "pending"),
            "pledged_usd": sum(u.get("amount_usd") or 0 for u in users), "by_plan": by_plan, "by_risk": by_risk,
            "active_wallets": sum(1 for w in tw if w.get("started")), "capital_under_bot_usd": round(sum(w.get("equity_usd") or 0 for w in tw if w.get("started")), 2),
            "pnl_usd": round(sum(w.get("pnl_usd") or 0 for w in tw if w.get("started")), 2),
            "fees_usd": round(sum((s.get("fees_usd") or 0) for s in (_summary(STATE / "users" / "_all.json") or {}).get("stools", [])), 2),
            "house_fee_wallet": (_summary(STATE / "users" / "_all.json") or {}).get("house_wallet"),
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
            if u.path == "/api/book":
                b = book_view(full=True)
                return self._send(200, b) if b else self._send(404, {"error": "The book is not open yet."})
            if u.path == "/api/lab":
                return self._send(200, lab_public())
            if u.path == "/api/ideas":
                return self._send(200, ideas_public())
            if u.path == "/api/admin/ideas":
                return self._send(200, ideas_admin())
            if u.path == "/api/expect":
                return self._send(200, expect(int(q.get("risk", 35))))
            if u.path == "/api/admin/book":
                b = book_view(full=True, admin=True)
                return self._send(200, b) if b else self._send(404, {"error": "The book is not open yet."})
            if u.path == "/api/admin/research":
                return self._send(200, research())
            if u.path == "/api/config":
                return self._send(200, {"fees": FEES, "risk_levels": RISK_LEVELS, "profit_rules": PROFIT_RULES,
                                        "plans": {k: {"name": v["nombre"], "markets": v["mercados"]} for k, v in PLANS.items()}})
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
                d = _summary(STATE / f"plan_{k}_summary.json") if k in PLAN_KEYS + ("lloyd",) else None
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
        if path == "/api/admin/seat":
            code, out = admin_seat(b); return self._send(code, out)
        if path == "/api/admin/ideas":
            code, out = idea_review(b); return self._send(code, out)
        if path == "/api/ideas":
            if not _rate_ok("id:" + ip, 3) or not _rate_ok("idd:" + ip, 8, 86400):
                return self._send(429, {"error": "Lloyd has your ideas for now. Try again in an hour."})
            code, out = idea_submit(b, ip, user_by_token(self._token())); return self._send(code, out)
        if path == "/api/ideas/vote":
            if not _rate_ok("iv:" + ip, 60): return self._send(429, {"error": "Too many votes. Try again later."})
            code, out = idea_vote(b, ip, user_by_token(self._token())); return self._send(code, out)
        usr = user_by_token(self._token())
        if not usr:
            return self._send(401, {"error": "Not logged in."})
        if path == "/api/me/settings":
            code, out = save_settings(usr, b); return self._send(code, out)
        if path == "/api/me/close_all":
            code, out = close_all(usr); return self._send(code, out)
        if path == "/api/me/withdraw":
            code, out = withdraw(usr); return self._send(code, out)
        if path == "/api/me/resume":
            code, out = resume(usr); return self._send(code, out)
        if path == "/api/me/tip":
            code, out = tip_lab(usr, b); return self._send(code, out)
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
