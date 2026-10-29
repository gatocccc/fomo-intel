"""Billeteras de usuarios ("stools"): un servicio que sigue al libro de Lloyd, una billetera por usuario (decisión de Gastón, 29/10/2026).

Qué hace, cada 15 s, para cada usuario con asiento (users.status = 'seated' en la base de la app):
- Si no tiene billetera, la crea (secrets/users/<id>.json) y la anota en la base (bot_wallet) para que la app muestre dónde depositar.
- Arranca cuando la billetera recibe SOL (>= MIRROR_MIN_SOL). Al arrancar copia la composición actual del libro (tokens y USDC) en proporción.
- Replica cada operación nueva del libro (state/plan_lloyd/trades.jsonl) en proporción patrimonio_usuario / patrimonio_libro:
  compras y ventas de tokens y también los pases a USDC (así el usuario está en dólares cuando Lloyd está en dólares).
- Comisión de ejecución, embebida: en cada compra/venta de TOKENS (no en USDC) se aparta FEE% del monto (1% holders, 1,5% externos)
  y se acumula; se transfiere a la billetera de la casa (secrets/house_fees.json) cuando junta >= 0.02 SOL, para no gastar gas en cada una.
- Piso: si el patrimonio cae 60% desde lo depositado, vende todo a SOL y se detiene (HALT), como en los planes.
- Pedidos de la app (marcas en state/users/): <id>_CLOSE vende todo a SOL; <id>_WITHDRAW manda el SOL (menos la reserva) a la billetera del usuario.
- Publica state/users/<id>_summary.json (la app lo sirve en /api/me) y state/users/_all.json (admin).

Operaciones chicas: no se replican las de menos de MIRROR_MIN_LEG_USD (US$10) salvo que cierren una posición. Prioridad baja por defecto.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

from ..live.config import Env, LiveParams
from ..live.executor import RealExecutor
from ..live.signals import STClient
from ..live.wallet import Rpc, load_or_create

log = logging.getLogger("mirror")
STATE = Path(os.getenv("FOMO_STATE_DIR", "state"))
UDIR = STATE / "users"; UDIR.mkdir(parents=True, exist_ok=True)
DB = STATE / "app" / "app.db"
LLOYD = STATE / "plan_lloyd"
LLOYD_SUMMARY = STATE / "plan_lloyd_summary.json"
SECRETS = Path("secrets/users"); SECRETS.mkdir(parents=True, exist_ok=True)
HOUSE = Path("secrets/house_fees.json")
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
STABLES = {USDC, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
MIN_SOL = float(os.getenv("MIRROR_MIN_SOL", "0.2"))          # con esto arranca (la app pide US$300 al público; en la prueba, menos)
MIN_LEG_USD = float(os.getenv("MIRROR_MIN_LEG_USD", "10"))
RESERVE_SOL = float(os.getenv("MIRROR_RESERVE_SOL", "0.02"))
FEE_HOLDER = float(os.getenv("FEE_TRADE_HOLDER_PCT", "1")) / 100
FEE_EXTERNAL = float(os.getenv("FEE_TRADE_EXTERNAL_PCT", "1.5")) / 100
FEE_SWEEP_SOL = 0.02
FLOOR_FRAC = 0.4


def jl(p, d=None):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def js(p, obj):
    p = Path(p); tmp = p.with_suffix(p.suffix + ".tmp")
    json.dump(obj, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def tail(p, n=300):
    p = Path(p)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines()[-n:]:
        try: out.append(json.loads(line))
        except Exception: pass  # noqa: BLE001
    return out


def db():
    c = sqlite3.connect(DB, timeout=10); c.row_factory = sqlite3.Row
    return c


class Stool:
    """La billetera de un usuario."""

    def __init__(self, svc: "Mirror", row: sqlite3.Row):
        self.svc = svc; self.uid = int(row["id"]); self.row = row
        self.dir = UDIR / str(self.uid); self.dir.mkdir(parents=True, exist_ok=True)
        self.kp = load_or_create(SECRETS / f"{self.uid}.json"); self.pub = str(self.kp.pubkey())
        p = LiveParams(); p.max_slippage_pct = 10.0; p.swap_slippage_pct = 12.0; p.min_sol_reserve = RESERVE_SOL
        p.priority_fee_sol = float(os.getenv("MIRROR_PRIORITY_FEE_SOL", "0.0003"))
        self.exe = RealExecutor(p, self.kp, svc.rpc, svc.env.solanatracker_api_key)
        self.cfg = jl(self.dir / "config.json", {}) or {"start_ts": None, "deposited_usd": 0.0, "deposited_sol": 0.0, "withdrawn_sol": 0.0, "expected_sol": 0.0,
                                                         "fee_pct": None, "fees_sol": 0.0, "fees_pending_sol": 0.0, "fees_paid_sol": 0.0, "halt": False, "closed": False}
        self.pos: dict = jl(self.dir / "positions.json", {}) or {}
        self.seen: list = jl(self.dir / "processed.json", []) or []
        self.sol = 0.0
        self.refresh_type()

    # ---------- registro ----------
    def save(self):
        js(self.dir / "config.json", self.cfg); js(self.dir / "positions.json", self.pos); js(self.dir / "processed.json", self.seen[-2000:])

    def append(self, name, row):
        with open(self.dir / name, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def journal(self, title, text, kind="auto"):
        self.append("journal.jsonl", {"ts": time.time(), "title": title, "text": text, "kind": kind})

    def refresh_type(self):
        holder = self.row["holder_status"] in ("holder", "pending")
        self.cfg["type"] = "holder" if holder else "external"
        self.cfg["fee_pct"] = FEE_HOLDER if holder else FEE_EXTERNAL

    # ---------- plata ----------
    def balance(self):
        try:
            self.sol = self.svc.rpc.sol_balance(self.pub)
        except Exception:  # noqa: BLE001
            pass
        return self.sol

    def detect_deposit(self):
        """SOL que apareció sin que lo hayamos movido nosotros = depósito."""
        diff = self.sol - float(self.cfg.get("expected_sol") or 0)
        if diff > 0.005:
            usd = diff * self.svc.sol_usd
            self.cfg["deposited_sol"] = round(self.cfg.get("deposited_sol", 0) + diff, 6)
            self.cfg["deposited_usd"] = round(self.cfg.get("deposited_usd", 0) + usd, 2)
            self.cfg["expected_sol"] = self.sol
            self.append("flows.jsonl", {"ts": time.time(), "kind": "deposit", "sol": round(diff, 6), "usd": round(usd, 2)})
            self.journal("Deposit received", f"{diff:.4f} SOL (${usd:.2f}) arrived in your stool.", kind="system")
            self.save()
            return diff
        return 0.0

    def equity(self):
        tokens_usd = 0.0
        for m, p in self.pos.items():
            px = self.svc.price(m) or p.get("last_usd") or p.get("entry_usd") or 0
            p["last_usd"] = px; tokens_usd += p["tokens"] * px
        return self.sol * self.svc.sol_usd + tokens_usd, tokens_usd

    # ---------- comisión ----------
    def resync_expected(self):
        """Después de mover plata nosotros, el saldo real es el nuevo punto de partida para detectar depósitos."""
        self.balance(); self.cfg["expected_sol"] = self.sol

    def take_fee(self, sol_amount: float, side: str, symbol: str) -> float:
        fee = sol_amount * float(self.cfg["fee_pct"])
        self.cfg["fees_sol"] = round(self.cfg.get("fees_sol", 0) + fee, 6)
        self.cfg["fees_pending_sol"] = round(self.cfg.get("fees_pending_sol", 0) + fee, 6)
        self.append("fees.jsonl", {"ts": time.time(), "side": side, "symbol": symbol, "sol": round(fee, 6), "pct": self.cfg["fee_pct"]})
        return fee

    def sweep_fees(self):
        pend = float(self.cfg.get("fees_pending_sol") or 0)
        if pend < FEE_SWEEP_SOL or self.sol - pend < RESERVE_SOL:
            return
        sig = self.svc.transfer(self.kp, self.svc.house_pub, pend)
        if sig:
            self.cfg["fees_pending_sol"] = 0.0; self.cfg["fees_paid_sol"] = round(self.cfg.get("fees_paid_sol", 0) + pend, 6)
            self.resync_expected()
            self.append("fees.jsonl", {"ts": time.time(), "side": "sweep", "sol": round(pend, 6), "sig": sig}); self.save()

    # ---------- órdenes ----------
    def buy(self, mint: str, symbol: str, sol: float, why: str, meta: dict | None = None) -> str:
        if self.cfg.get("halt") or self.cfg.get("closed"):
            return "stool stopped"
        is_token = mint not in STABLES
        fee = sol * float(self.cfg["fee_pct"]) if is_token else 0.0
        spend = sol - fee
        avail = self.sol - RESERVE_SOL - float(self.cfg.get("fees_pending_sol") or 0)
        if spend > avail:
            spend = round(avail - 0.003, 5)
        if spend * self.svc.sol_usd < 2:
            return f"not enough SOL ({self.sol:.4f})"
        px = self.svc.price(mint)
        if not px:
            return "no price"
        f = self.exe.buy(mint, round(spend, 5), px / self.svc.sol_usd)
        self.append("trades.jsonl", {"ts": time.time(), "side": "buy", "mint": mint, "symbol": symbol, "ok": f.ok, "sol": f.sol, "tokens": f.tokens,
                                     "price_usd": round(f.price * self.svc.sol_usd, 12) if f.ok else None, "slip": f.slippage_pct, "fee_sol": round(fee, 6), "sig": f.sig, "error": f.error[:200], "why": why})
        if not f.ok:
            return f"buy failed: {f.error[:120]}"
        if fee:
            self.take_fee(sol, "buy", symbol)
        self.resync_expected()
        entry = f.price * self.svc.sol_usd
        cur = self.pos.get(mint)
        if cur:
            tok = cur["tokens"] + f.tokens
            cur["entry_usd"] = (cur["entry_usd"] * cur["tokens"] + entry * f.tokens) / tok
            cur["tokens"] = tok; cur["sol_in"] += f.sol
        else:
            self.pos[mint] = {"mint": mint, "symbol": symbol, "opened_ts": time.time(), "entry_usd": entry, "tokens": f.tokens, "sol_in": f.sol, "sol_out": 0.0,
                              "sleeve": (meta or {}).get("sleeve") or ("cash" if not is_token else "picks"), "thesis": (meta or {}).get("thesis", "")}
        self.save()
        return f"bought {f.tokens:,.2f} {symbol} for {f.sol:.4f} SOL"

    def sell(self, mint: str, frac: float, why: str) -> str:
        p = self.pos.get(mint)
        if not p:
            return "no position"
        tokens = p["tokens"] if frac >= 0.98 else p["tokens"] * frac
        px = self.svc.price(mint) or p.get("last_usd") or p["entry_usd"]
        f = None
        for i in range(3):
            f = self.exe.sell(mint, tokens, px / self.svc.sol_usd, fast=i == 2)
            if f.ok or "sin tokens" in f.error:
                break
            time.sleep(3)
        is_token = mint not in STABLES
        fee = self.take_fee(f.sol, "sell", p["symbol"]) if (f.ok and is_token) else 0.0
        self.append("trades.jsonl", {"ts": time.time(), "side": "sell", "mint": mint, "symbol": p["symbol"], "ok": f.ok, "sol": f.sol, "tokens": f.tokens,
                                     "price_usd": round(f.price * self.svc.sol_usd, 12) if f.ok else None, "fee_sol": round(fee, 6), "sig": f.sig, "error": f.error[:200], "why": why})
        if not f.ok and "sin tokens" not in f.error:
            return f"sell failed: {f.error[:120]}"
        if f.ok:
            self.resync_expected()
        p["tokens"] = max(0.0, p["tokens"] - (f.tokens if f.ok else p["tokens"])); p["sol_out"] += f.sol if f.ok else 0.0
        if p["tokens"] * px < 0.5 or "sin tokens" in (f.error or ""):
            pnl = p["sol_out"] - p["sol_in"]
            self.append("closed.jsonl", {"ts": time.time(), "mint": mint, "symbol": p["symbol"], "sol_in": round(p["sol_in"], 5), "sol_out": round(p["sol_out"], 5),
                                         "pnl_sol": round(pnl, 5), "pnl_usd": round(pnl * self.svc.sol_usd, 2), "ret": round(p["sol_out"] / p["sol_in"] - 1, 3) if p["sol_in"] else None,
                                         "hold_h": round((time.time() - p["opened_ts"]) / 3600, 1), "why": why, "sleeve": p.get("sleeve")})
            self.pos.pop(mint, None)
        self.save()
        return f"sold {frac:.0%} of {p['symbol']} for {f.sol:.4f} SOL"

    # ---------- seguir al libro ----------
    def ratio(self) -> float:
        """Patrimonio del usuario / patrimonio del libro: con eso se escala cada operación."""
        eq, _ = self.equity(); book = float(self.svc.book.get("equity_usd") or 0)
        return eq / book if book > 0 else 0.0

    def start(self):
        if self.cfg.get("start_ts") or self.sol < MIN_SOL:
            return
        self.cfg["start_ts"] = time.time(); self.cfg["start_usd"] = round(self.sol * self.svc.sol_usd, 2)
        self.cfg["floor_usd"] = round(self.cfg["start_usd"] * FLOOR_FRAC, 2)
        self.seen = [t.get("sig") for t in tail(LLOYD / "trades.jsonl", 500) if t.get("sig")]   # lo anterior al arranque no se replica
        self.journal("Your stool is open", f"Lloyd starts trading for you with {self.sol:.4f} SOL (${self.cfg['start_usd']:.2f}). "
                     f"Hard floor: ${self.cfg['floor_usd']:.0f}; if your stool ever loses 60%, everything is sold and it stops.", kind="system")
        self.save()
        self.sync_to_book()

    def sync_to_book(self):
        """Copia la composición actual del libro: cada posición (tokens y USDC) en la misma proporción."""
        r = self.ratio()
        res = []
        for bp in self.svc.book.get("positions") or []:
            val = float(bp.get("value_usd") or 0) * r
            if val < MIN_LEG_USD:
                continue
            res.append(f"{bp.get('symbol')}: " + self.buy(bp["mint"], bp.get("symbol") or bp["mint"][:6], val / self.svc.sol_usd, "copying the book", {"sleeve": bp.get("sleeve"), "thesis": bp.get("thesis")}))
        if res:
            self.journal("Matched the book", "Your stool now holds what Lloyd holds, in proportion:\n" + "\n".join(res), kind="auto")

    def follow(self):
        if not self.cfg.get("start_ts") or self.cfg.get("halt") or self.cfg.get("closed"):
            return
        lloyd_pos = jl(LLOYD / "positions.json", {}) or {}
        for t in tail(LLOYD / "trades.jsonl", 200):
            sig = t.get("sig")
            if not sig or sig in self.seen or not t.get("ok") or float(t.get("ts") or 0) < float(self.cfg["start_ts"]):
                continue
            self.seen.append(sig)
            mint, sym = t["mint"], t.get("symbol") or t["mint"][:6]
            r = self.ratio()
            if r <= 0:
                continue
            why = f"following the book: {t.get('why') or t.get('id') or 'Lloyd'}"
            try:
                if t["side"] == "buy":
                    sol = float(t["sol"]) * r
                    if sol * self.svc.sol_usd < MIN_LEG_USD:
                        self.append("skipped.jsonl", {"ts": time.time(), "sig": sig, "symbol": sym, "usd": round(sol * self.svc.sol_usd, 2), "why": "too small"}); continue
                    lp = lloyd_pos.get(mint) or {}
                    res = self.buy(mint, sym, sol, why, {"sleeve": lp.get("sleeve"), "thesis": lp.get("thesis")})
                else:
                    if mint not in self.pos:
                        continue
                    lp = lloyd_pos.get(mint)
                    frac = 1.0 if not lp or lp.get("tokens", 0) <= 0 else min(1.0, float(t["tokens"]) / (float(lp["tokens"]) + float(t["tokens"])))
                    val = self.pos[mint]["tokens"] * frac * (self.svc.price(mint) or self.pos[mint].get("last_usd") or 0)
                    if frac < 0.98 and val < MIN_LEG_USD:
                        self.append("skipped.jsonl", {"ts": time.time(), "sig": sig, "symbol": sym, "usd": round(val, 2), "why": "too small"}); continue
                    res = self.sell(mint, frac, why)
                self.journal("Lloyd moved, so did you", f"{sym}: {res}", kind="auto")
            except Exception as e:  # noqa: BLE001
                log.exception("stool %s: %s", self.uid, e); self.journal("Error", f"{sym}: {str(e)[:160]}", kind="system")
            self.save()
        # posiciones que el libro ya no tiene (por si se perdió una venta): salir, con 90 s de gracia por si el libro recién compró
        lloyd_pos = jl(LLOYD / "positions.json", lloyd_pos) or lloyd_pos
        miss = self.cfg.setdefault("_missing", {})
        for m in list(self.pos):
            if m in STABLES or self.pos[m]["tokens"] <= 0:
                continue
            if m in lloyd_pos:
                miss.pop(m, None); continue
            miss.setdefault(m, time.time())
            if time.time() - miss[m] > 90:
                sym = self.pos[m].get("symbol") or m[:6]
                res = self.sell(m, 1.0, "the book no longer holds it"); miss.pop(m, None)
                self.journal("Lloyd moved, so did you", f"{sym}: {res}", kind="auto")

    # ---------- piso, cierre y retiro ----------
    def floor_check(self, eq):
        if self.cfg.get("start_ts") and not self.cfg.get("halt") and eq < float(self.cfg.get("floor_usd") or 0):
            self.cfg["halt"] = True; self.save()
            self.close_all("hard floor")
            self.journal("Stool stopped", f"Your stool fell to ${eq:.2f}, below the ${self.cfg['floor_usd']:.0f} floor. Everything was sold to SOL and it stopped.", kind="system")

    def close_all(self, why="you asked"):
        res = [f"{p['symbol']}: {self.sell(m, 1.0, why)}" for m, p in list(self.pos.items())]
        self.cfg["closed"] = True; self.save()
        self.journal("Everything to SOL", "\n".join(res) or "Nothing to sell.", kind="system")

    def requests(self):
        c = UDIR / f"{self.uid}_CLOSE"; w = UDIR / f"{self.uid}_WITHDRAW"; t = UDIR / f"{self.uid}_TIP"
        if t.exists():
            try: sol = float((jl(t, {}) or {}).get("sol") or 0)
            except Exception: sol = 0.0  # noqa: BLE001
            t.unlink()
            lab = (jl(STATE / "plan_lab_summary.json", {}) or {}).get("wallet")
            self.balance()
            if lab and 0.01 <= sol <= 5 and self.sol - sol - float(self.cfg.get("fees_pending_sol") or 0) >= RESERVE_SOL:
                sig = self.svc.transfer(self.kp, lab, sol)
                if sig:
                    self.resync_expected(); self.cfg["tipped_sol"] = round(self.cfg.get("tipped_sol", 0) + sol, 6)
                    self.append("flows.jsonl", {"ts": time.time(), "kind": "tip", "sol": sol, "usd": round(sol * self.svc.sol_usd, 2), "to": lab, "sig": sig}); self.save()
                    self.journal("You bought the lab a round", f"{sol} SOL went to Lloyd's lab wallet. Every experiment it funds ends up in your stool. Thank you.", kind="system")
                else:
                    self.journal("Tip did not go through", "The transfer did not confirm. Nothing was taken; try again.", kind="system")
            else:
                self.journal("Tip skipped", "Not enough free SOL in your stool for that tip right now (Lloyd keeps most of it at work).", kind="system")
        if c.exists():
            c.unlink(); self.close_all("you asked")
            with db() as d: d.execute("UPDATE users SET status='closed' WHERE id=?", (self.uid,))
        if w.exists():
            dest = (self.row["sol_wallet"] or "").strip(); w.unlink()
            if not dest:
                self.journal("Withdrawal skipped", "No Solana wallet on file.", kind="system"); return
            if self.pos:
                self.close_all("withdrawal")
            self.balance(); amt = round(self.sol - RESERVE_SOL - float(self.cfg.get("fees_pending_sol") or 0) - 0.002, 5)
            if amt <= 0.001:
                self.journal("Withdrawal skipped", "Nothing left to send after the network reserve.", kind="system"); return
            sig = self.svc.transfer(self.kp, dest, amt)
            if sig:
                self.cfg["withdrawn_sol"] = round(self.cfg.get("withdrawn_sol", 0) + amt, 6); self.resync_expected()
                self.append("flows.jsonl", {"ts": time.time(), "kind": "withdraw", "sol": amt, "usd": round(amt * self.svc.sol_usd, 2), "to": dest, "sig": sig}); self.save()
                self.journal("Withdrawn", f"{amt:.4f} SOL sent to {dest}.", kind="system")
            else:
                self.journal("Withdrawal failed", "The transfer did not confirm. It will not be retried automatically; ask again.", kind="system")

    # ---------- publicar ----------
    def publish(self, eq, tokens_usd):
        now = time.time(); c = self.cfg; su = self.svc.sol_usd
        dep = float(c.get("deposited_usd") or 0); wd = float(c.get("withdrawn_sol") or 0) * su
        if c.get("start_ts") and now - float(c.get("_last_eq") or 0) > 300:
            self.append("equity.jsonl", {"ts": now, "usd": round(eq, 2), "sol": round(eq / su, 4), "sol_usd": round(su, 2)}); c["_last_eq"] = now; self.save()
        s = {"now": now, "user_id": self.uid, "wallet": self.pub, "type": c.get("type"), "fee_pct": c.get("fee_pct"), "started": bool(c.get("start_ts")), "since": c.get("start_ts"),
             "halt": bool(c.get("halt")), "closed": bool(c.get("closed")), "sol_usd": round(su, 2), "cash_sol": round(self.sol, 4),
             "equity_usd": round(eq, 2), "deposited_usd": round(dep, 2), "withdrawn_usd": round(wd, 2), "pnl_usd": round(eq + wd + float(c.get("tipped_sol") or 0) * su - dep, 2) if dep else None,
             "pnl_pct": round((eq + wd + float(c.get("tipped_sol") or 0) * su) / dep - 1, 4) if dep else None, "fees_usd": round(float(c.get("fees_sol") or 0) * su, 2), "min_sol": MIN_SOL,
             "positions": [{"token": p["symbol"], "mint": m, "sleeve": p.get("sleeve"), "multiple": round((p.get("last_usd") or p["entry_usd"]) / p["entry_usd"], 3) if p["entry_usd"] else None,
                            "value_usd": round(p["tokens"] * (p.get("last_usd") or p["entry_usd"]), 2), "opened": p.get("opened_ts"), "thesis": p.get("thesis")} for m, p in self.pos.items() if m not in STABLES],
             "cash_usd": round(self.sol * su + sum(p["tokens"] * (p.get("last_usd") or 1) for m, p in self.pos.items() if m in STABLES), 2),
             "equity": [[round(h["ts"]), h["usd"]] for h in tail(self.dir / "equity.jsonl", 2000)],
             "closed": tail(self.dir / "closed.jsonl", 100)[::-1], "trades": tail(self.dir / "trades.jsonl", 60)[::-1], "journal": tail(self.dir / "journal.jsonl", 100)[::-1]}
        js(UDIR / f"{self.uid}_summary.json", s)
        return s


class Mirror:
    def __init__(self):
        self.env = Env(); self.rpc = Rpc(self.env.rpc_url); self.st = STClient(self.env.solanatracker_api_key)
        self.house_pub = str(load_or_create(HOUSE).pubkey())
        self.jup_key = os.getenv("JUPITER_API_KEY", "")
        self.sol_usd = self.st.sol_usd() or 100.0; self.prices: dict = {}; self.price_ts: dict = {}
        self.book: dict = jl(LLOYD_SUMMARY, {}) or {}
        self.stools: dict[int, Stool] = {}

    def price(self, mint):
        if mint in STABLES:
            return 1.0
        if time.time() - self.price_ts.get(mint, 0) < 20 and mint in self.prices:
            return self.prices[mint]
        px = None
        for bp in self.book.get("positions") or []:            # el libro ya tiene precio fresco de lo que tiene
            if bp.get("mint") == mint and bp.get("last_usd"):
                px = float(bp["last_usd"]); break
        if not px and self.jup_key:
            try:
                import requests
                d = requests.get("https://api.jup.ag/price/v3", params={"ids": mint}, headers={"x-api-key": self.jup_key}, timeout=8).json().get(mint) or {}
                px = float(d.get("usdPrice") or 0) or None
            except Exception:  # noqa: BLE001
                px = None
        if not px:
            px = self.st.price(mint)
        if px:
            self.prices[mint] = px; self.price_ts[mint] = time.time()
        return px or self.prices.get(mint)

    def transfer(self, kp, dest: str, sol: float) -> str | None:
        from solders.hash import Hash
        from solders.instruction import Instruction
        from solders.pubkey import Pubkey
        from solders.system_program import TransferParams, transfer
        from solders.transaction import Transaction
        CB = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
        ixs = [Instruction(CB, bytes([2]) + (60_000).to_bytes(4, "little"), []), Instruction(CB, bytes([3]) + (100_000).to_bytes(8, "little"), []),
               transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=Pubkey.from_string(dest), lamports=int(sol * 1e9)))]
        for _ in range(3):
            try:
                bh = self.rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
                tx = Transaction.new_signed_with_payer(ixs, kp.pubkey(), [kp], Hash.from_string(bh))
                sig = self.rpc.send_raw(base64.b64encode(bytes(tx)).decode())
                if self.rpc.wait_confirmed(sig, 75):
                    return sig
            except Exception as e:  # noqa: BLE001
                log.warning("transfer: %s", e); time.sleep(3)
        return None

    def load_users(self):
        if not DB.exists():
            return
        with db() as c:
            rows = c.execute("SELECT * FROM users WHERE status IN ('seated','closing','closed')").fetchall()
            for r in rows:
                uid = int(r["id"])
                if uid not in self.stools:
                    self.stools[uid] = Stool(self, r)
                    if not r["bot_wallet"]:
                        c.execute("UPDATE users SET bot_wallet=? WHERE id=?", (self.stools[uid].pub, uid))
                        log.info("stool %s: wallet %s", uid, self.stools[uid].pub)
                else:
                    self.stools[uid].row = r; self.stools[uid].refresh_type()
            live = {int(r["id"]) for r in rows}
        for uid in list(self.stools):
            if uid not in live:
                self.stools.pop(uid)

    def run(self):
        last_sol = last_users = last_pub = 0.0
        while True:
            now = time.time()
            try:
                if now - last_sol > 120:
                    self.sol_usd = self.st.sol_usd(60) or self.sol_usd; last_sol = now
                if now - last_users > 30:
                    self.load_users(); last_users = now
                self.book = jl(LLOYD_SUMMARY, self.book) or self.book
                allp = []
                for s in list(self.stools.values()):
                    try:
                        s.balance(); s.detect_deposit(); s.start(); s.requests(); s.follow()
                        eq, tu = s.equity(); s.floor_check(eq); s.sweep_fees()
                        if now - last_pub > 30:
                            allp.append({k: v for k, v in s.publish(eq, tu).items() if k not in ("equity", "closed", "trades", "journal", "positions")} | {"email": s.row["email"], "name": s.row["name"]})
                    except Exception as e:  # noqa: BLE001
                        log.exception("stool %s: %s", s.uid, e)
                if now - last_pub > 30:
                    js(UDIR / "_all.json", {"now": now, "house_wallet": self.house_pub, "stools": allp}); last_pub = now
            except Exception as e:  # noqa: BLE001
                log.exception("ciclo: %s", e)
            time.sleep(15)


def main():
    from ..live.bot import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Mirror().run()


if __name__ == "__main__":
    main()
