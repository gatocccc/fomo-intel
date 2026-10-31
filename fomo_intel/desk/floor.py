"""Lotería en el piso (31/10/2026) — prueba hacia adelante con dinero real chico, billetera propia.

Hallazgo del censo (ops 220, doc del Project censo-memecoins-31-10): comprar un lanzamiento de pump.fun en el PRIMER minuto,
cuando su valuación sigue cerca del piso de la curva (<= 1,30x el valor inicial), acota la pérdida a ~6-8% (la curva no deja caer
el precio por debajo del inicial) y deja abierta la cola (1 de cada ~400 hizo 50-60x). Media +6% por ticket con datos crudos,
pero sin el 1% mejor da -9%: es una lotería. Al minuto 2 ya era negativa. Esto mide si en vivo se cumple.

Regla (congelada para la prueba):
  - fuente: PumpPortal subscribeNewToken (gratis). Cada lanzamiento se mira una vez entre 50 y 100 s de vida.
  - entrada: curva no completa y valuación <= FLOOR_RATIO x piso (piso = 30 SOL virtuales / 1.073e9 tokens -> ~27,96 SOL).
    Como máximo un ticket cada FLOOR_GAP_S y FLOOR_MAX_DAY por día (hora BA). Ticket FLOOR_TICKET_SOL.
  - salida: 34% al tocar 3x; el resto con trailing 40% desde el pico (solo después de tocar 3x); a las 6 h se vende todo.
    Sin stop: el piso es el stop.
  - frenos: no abre si el SOL libre < FLOOR_MIN_SOL; modo en state/desk/floor_mode (live | shadow | off) o env FLOOR_MODE.
Archivos: state/desk/floor.json (resumen), floor_pos.json (abiertas), floor_closed.jsonl (cerradas), floor_log.jsonl (eventos),
          floor_cands.jsonl (todos los candidatos elegibles, para medir en sombra la frecuencia de la cola).
Billetera: secrets/plan_floor.json (se crea sola la primera vez).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import struct
import threading
import time
from pathlib import Path

import requests

from ..live.bot import load_dotenv
from ..live.config import Env, LiveParams
from ..live.executor import RealExecutor
from ..live.wallet import Rpc, load_or_create

log = logging.getLogger("floor")
D = Path("state/desk")
SUMMARY, POS, CLOSED, LOG, CANDS = D / "floor.json", D / "floor_pos.json", D / "floor_closed.jsonl", D / "floor_log.jsonl", D / "floor_cands.jsonl"
MODE_FILE = D / "floor_mode"
WALLET = Path(os.getenv("FLOOR_WALLET", "secrets/plan_floor.json"))
WS = "wss://pumpportal.fun/api/data"
JUP_PRICE = "https://api.jup.ag/price/v3"
SOL_MINT = "So11111111111111111111111111111111111111112"
FLOOR_SOL = 30.0 / 1_073_000_000 * 1e9          # valuación inicial de la curva en SOL (~27,96)

TICKET = float(os.getenv("FLOOR_TICKET_SOL", "0.025"))
RATIO = float(os.getenv("FLOOR_RATIO", "1.30"))
GAP_S = float(os.getenv("FLOOR_GAP_S", "720"))        # 12 min -> 5 por hora (31/10 11:48: Gastón pidió acelerar)
MAX_DAY = int(os.getenv("FLOOR_MAX_DAY", "100"))
MIN_SOL = float(os.getenv("FLOOR_MIN_SOL", "0.05"))
EVAL_LO, EVAL_HI = 50.0, 100.0
REC_K, REC_FRAC, TRAIL, MAX_HOLD = 3.0, 0.34, 0.40, 6 * 3600


def jl(p: Path, row: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ba_day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts - 3 * 3600))


def curve_state(data_b64: str) -> dict | None:
    """Cuenta bonding curve de pump.fun: disc(8) vTok vSol rTok rSol supply (u64) complete(bool)."""
    try:
        raw = base64.b64decode(data_b64)
        vt, vs, rt, rs, sup = struct.unpack_from("<QQQQQ", raw, 8)
        complete = bool(raw[48])
        if vt <= 0:
            return None
        price = (vs / 1e9) / (vt / 1e6)          # SOL por token
        return {"price": price, "mcap_sol": price * 1e9, "complete": complete, "real_sol": rs / 1e9}
    except Exception:  # noqa: BLE001
        return None


class Floor:
    def __init__(self):
        load_dotenv()
        self.env = Env(); self.rpc = Rpc(self.env.rpc_url)
        self.kp = load_or_create(WALLET); self.pub = str(self.kp.pubkey())
        p = LiveParams(); p.mode = "real"; p.priority_fee_sol = float(os.getenv("FLOOR_PRIORITY_SOL", "0.00005"))
        p.swap_slippage_pct = 15.0; p.max_slippage_pct = 30.0
        self.ex = RealExecutor(p, self.kp, self.rpc, self.env.solanatracker_api_key)
        self.jup_key = os.getenv("JUP_API_KEY", "")
        self.lock = threading.RLock()
        self.pending: dict[str, dict] = {}       # mint -> {ts, curve, sym}
        self.pos: dict[str, dict] = json.load(open(POS)) if POS.exists() else {}
        self.last_buy = max([p.get("ts", 0) for p in self.pos.values()] or [0])
        self.stats = {"seen": 0, "evaluated": 0, "eligible": 0, "bought": 0, "buy_fail": 0, "closed": 0, "ws_reconnects": 0}
        self.sol_usd = 0.0; self.sol_usd_ts = 0.0
        self.buying = False

    # ---------------- utilidades ----------------
    def mode(self) -> str:
        try:
            m = MODE_FILE.read_text().strip()
            if m in ("live", "shadow", "off"):
                return m
        except OSError:
            pass
        return os.getenv("FLOOR_MODE", "live")

    def sol_price(self) -> float:
        if time.time() - self.sol_usd_ts > 300:
            try:
                d = requests.get(JUP_PRICE, params={"ids": SOL_MINT}, headers={"x-api-key": self.jup_key} if self.jup_key else {}, timeout=8).json()
                self.sol_usd = float((d.get(SOL_MINT) or {}).get("usdPrice") or self.sol_usd); self.sol_usd_ts = time.time()
            except Exception:  # noqa: BLE001
                pass
        return self.sol_usd

    def curves(self, keys: list[str]) -> dict[str, dict | None]:
        out = {}
        for i in range(0, len(keys), 100):
            chunk = keys[i:i + 100]
            try:
                res = self.rpc.call("getMultipleAccounts", [chunk, {"encoding": "base64", "commitment": "confirmed"}]) or {}
                for k, acc in zip(chunk, res.get("value") or []):
                    out[k] = curve_state(acc["data"][0]) if acc else None
            except Exception as e:  # noqa: BLE001
                log.warning("getMultipleAccounts: %s", e)
        return out

    def jup_prices(self, mints: list[str]) -> dict[str, float]:
        out = {}
        for i in range(0, len(mints), 50):
            try:
                d = requests.get(JUP_PRICE, params={"ids": ",".join(mints[i:i + 50])}, headers={"x-api-key": self.jup_key} if self.jup_key else {}, timeout=10).json()
                for m, v in (d or {}).items():
                    if v and v.get("usdPrice"):
                        out[m] = float(v["usdPrice"])
            except Exception:  # noqa: BLE001
                pass
        return out

    def save(self) -> None:
        with self.lock:
            D.mkdir(parents=True, exist_ok=True)
            json.dump(self.pos, open(POS, "w"), indent=1)
            closed = []
            if CLOSED.exists():
                for l in open(CLOSED):
                    try: closed.append(json.loads(l))
                    except Exception: pass  # noqa: BLE001,E701
            pnl = sum(c.get("pnl_sol", 0) for c in closed)
            inv = sum(c.get("cost_sol", 0) for c in closed)
            best = max(closed, key=lambda c: c.get("mult", 0), default=None)
            today = ba_day(time.time())
            try:
                bal = self.rpc.sol_balance(self.pub)
            except Exception:  # noqa: BLE001
                bal = None
            open_val = sum((q.get("last_px") or q["entry_px"]) * q["tokens"] for q in self.pos.values())
            start_p = D / "floor_start.json"
            if bal is not None and not start_p.exists():
                json.dump({"ts": time.time(), "start_sol": round(bal + sum(q["cost_sol"] for q in self.pos.values()) - pnl, 6)}, open(start_p, "w"))
            start = (json.load(open(start_p)) if start_p.exists() else {}).get("start_sol")
            equity = (bal + open_val) if bal is not None else None
            json.dump({"ts": time.time(), "mode": self.mode(), "start_sol": start, "equity_sol": round(equity, 5) if equity is not None else None,
                       "open_value_sol": round(open_val, 5),
                       "positions": [{"sym": q["sym"], "mint": m, "mult": round((q.get("last_px") or q["entry_px"]) / q["entry_px"], 3),
                                      "peak_mult": round(q["peak_px"] / q["entry_px"], 2), "ts": q["ts"], "hit_rec": q["hit_rec"]}
                                     for m, q in sorted(self.pos.items(), key=lambda kv: -kv[1]["ts"])],
                       "recent_closed": [{k: c.get(k) for k in ("sym", "mint", "mult", "peak_mult", "pnl_sol", "why", "closed_ts", "hold_min")} for c in closed[-12:][::-1]], "wallet": self.pub, "sol_balance": bal, "sol_usd": self.sol_usd,
                       "ticket_sol": TICKET, "ratio": RATIO, "open": len(self.pos), "open_cost_sol": round(sum(p["cost_sol"] for p in self.pos.values()), 4),
                       "closed": len(closed), "closed_pnl_sol": round(pnl, 4), "closed_cost_sol": round(inv, 4),
                       "closed_roi": round(pnl / inv, 4) if inv else None, "wins_3x": sum(1 for c in closed if c.get("hit_rec")),
                       "best": {k: best.get(k) for k in ("sym", "mint", "mult", "pnl_sol")} if best else None,
                       "bought_today": sum(1 for p in list(self.pos.values()) + closed if ba_day(p.get("ts", 0)) == today),
                       "stats": self.stats}, open(SUMMARY, "w"), indent=1)

    # ---------------- stream ----------------
    def ws_loop(self) -> None:
        import websocket
        while True:
            try:
                ws = websocket.create_connection(WS, timeout=30)
                ws.send(json.dumps({"method": "subscribeNewToken"}))
                log.info("PumpPortal conectado")
                while True:
                    raw = ws.recv()
                    if not raw:
                        continue
                    try:
                        m = json.loads(raw)
                    except ValueError:
                        continue
                    if m.get("txType") == "create" and m.get("mint") and m.get("bondingCurveKey"):
                        self.stats["seen"] += 1
                        with self.lock:
                            self.pending[m["mint"]] = {"ts": time.time(), "curve": m["bondingCurveKey"], "sym": (m.get("symbol") or "")[:20],
                                                       "name": (m.get("name") or "")[:40], "creator": m.get("traderPublicKey"),
                                                       "mcap0": m.get("marketCapSol"), "pool": m.get("pool")}
            except Exception as e:  # noqa: BLE001
                self.stats["ws_reconnects"] += 1
                log.warning("PumpPortal: %s; reconecto en 5 s", e)
                time.sleep(5)

    # ---------------- evaluación ----------------
    def eval_loop(self) -> None:
        while True:
            time.sleep(2)
            now = time.time()
            with self.lock:
                due = {m: p for m, p in self.pending.items() if now - p["ts"] >= EVAL_LO}
                for m in due:
                    self.pending.pop(m, None)
                for m in [m for m, p in self.pending.items() if now - p["ts"] > 600]:
                    self.pending.pop(m, None)
            due = {m: p for m, p in due.items() if now - p["ts"] <= EVAL_HI and (p.get("pool") in (None, "pump"))}
            if not due:
                continue
            cs = self.curves([p["curve"] for p in due.values()])
            for mint, p in due.items():
                c = cs.get(p["curve"])
                self.stats["evaluated"] += 1
                # 0,95x: hay curvas con otros parámetros (valuación por debajo del piso estándar, ej. 9 SOL): ahí el piso no protege
                if not c or c["complete"] or not (0.95 * FLOOR_SOL <= c["mcap_sol"] <= RATIO * FLOOR_SOL):
                    continue
                self.stats["eligible"] += 1
                row = {"ts": now, "mint": mint, "sym": p["sym"], "age_s": round(now - p["ts"]), "mcap_sol": round(c["mcap_sol"], 2),
                       "mcap0_sol": p.get("mcap0"), "creator": p.get("creator")}
                jl(CANDS, row)
                self.maybe_buy(mint, p, c, row)

    def maybe_buy(self, mint: str, p: dict, c: dict, row: dict) -> None:
        mode = self.mode()
        if mode != "live" or self.buying:
            return
        now = time.time()
        if now - self.last_buy < GAP_S:
            return
        today = ba_day(now)
        n_today = sum(1 for q in self.pos.values() if ba_day(q["ts"]) == today)
        if CLOSED.exists():
            n_today += sum(1 for l in open(CLOSED) if ba_day(json.loads(l).get("ts", 0)) == today)
        if n_today >= MAX_DAY:
            return
        try:
            if self.rpc.sol_balance(self.pub) < MIN_SOL + TICKET:
                return
        except Exception:  # noqa: BLE001
            return
        self.buying = True; self.last_buy = now
        threading.Thread(target=self._buy, args=(mint, p, c, row), daemon=True).start()

    def _buy(self, mint: str, p: dict, c: dict, row: dict) -> None:
        try:
            # 31/10 17:40: precio fresco justo antes de enviar (el corrido medio era +8,6% contra una lectura de hasta 5 s)
            c2 = self.curves([p["curve"]]).get(p["curve"])
            if not c2 or c2["complete"] or c2["mcap_sol"] > RATIO * FLOOR_SOL:
                jl(LOG, {"ts": time.time(), "ev": "skip_moved", "mint": mint, "sym": p["sym"], "mcap_sol": c2 and round(c2["mcap_sol"], 2)}); return
            c = c2
            f = self.ex.buy(mint, TICKET, c["price"], fast=True)
            if not f.ok:
                self.stats["buy_fail"] += 1
                jl(LOG, {"ts": time.time(), "ev": "buy_fail", "mint": mint, "sym": p["sym"], "err": f.error, "latency_s": f.latency_s}); return
            self.stats["bought"] += 1
            with self.lock:
                self.pos[mint] = {"ts": time.time(), "mint": mint, "sym": p["sym"], "name": p.get("name"), "curve": p["curve"],
                                  "tokens": f.tokens, "tokens0": f.tokens, "cost_sol": f.sol, "entry_px": f.price, "ref_px": c["price"],
                                  "slip_pct": f.slippage_pct, "age_at_entry_s": row["age_s"], "mcap_sol_entry": row["mcap_sol"],
                                  "peak_px": f.price, "hit_rec": False, "proceeds_sol": 0.0, "sig": f.sig, "latency_s": f.latency_s}
            jl(LOG, {"ts": time.time(), "ev": "buy", "mint": mint, "sym": p["sym"], "sol": f.sol, "px": f.price, "ref_px": c["price"],
                     "slip_pct": f.slippage_pct, "latency_s": f.latency_s, "sig": f.sig})
            self.save()
        except Exception as e:  # noqa: BLE001
            jl(LOG, {"ts": time.time(), "ev": "buy_error", "mint": mint, "err": str(e)[:200]})
        finally:
            self.buying = False

    # ---------------- gestión ----------------
    def manage_loop(self) -> None:
        while True:
            time.sleep(30)
            try:
                self.manage()
            except Exception as e:  # noqa: BLE001
                log.warning("manage: %s", e)
            try:
                self.save()
            except Exception as e:  # noqa: BLE001
                log.warning("save: %s", e)

    def manage(self) -> None:
        with self.lock:
            pos = dict(self.pos)
        if not pos:
            return
        cs = self.curves([q["curve"] for q in pos.values()])
        done = [m for m, q in pos.items() if (cs.get(q["curve"]) or {}).get("complete") or cs.get(q["curve"]) is None]
        jp = self.jup_prices(done) if done else {}
        solp = self.sol_price()
        now = time.time()
        for mint, q in pos.items():
            c = cs.get(q["curve"])
            if c and not c["complete"]:
                px = c["price"]
            elif mint in jp and solp:
                px = jp[mint] / solp
            else:
                px = None
            if px:
                q["last_px"] = px; q["peak_px"] = max(q["peak_px"], px)
            e = q["entry_px"]
            if px and not q["hit_rec"] and px >= REC_K * e:
                self.sell(mint, q, q["tokens0"] * REC_FRAC, "rec_3x", partial=True); continue
            if px and q["hit_rec"] and px <= (1 - TRAIL) * q["peak_px"]:
                self.sell(mint, q, None, "trail"); continue
            if now - q["ts"] >= MAX_HOLD:
                self.sell(mint, q, None, "6h"); continue

    def sell(self, mint: str, q: dict, tokens: float | None, why: str, partial: bool = False) -> None:
        amt = tokens if tokens is not None else q["tokens"]
        f = self.ex.sell(mint, amt, q.get("last_px") or q["entry_px"], fast=True)
        if not f.ok:
            jl(LOG, {"ts": time.time(), "ev": "sell_fail", "mint": mint, "why": why, "err": f.error}); q["sell_fails"] = q.get("sell_fails", 0) + 1
            if q["sell_fails"] >= 5 and not partial:   # no se puede vender (sin liquidez): se da por cerrado en cero
                self._close(mint, q, why + "_unsellable")
            return
        with self.lock:
            q["proceeds_sol"] += f.sol; q["tokens"] = max(0.0, q["tokens"] - f.tokens)
            jl(LOG, {"ts": time.time(), "ev": "sell", "mint": mint, "sym": q["sym"], "why": why, "sol": f.sol, "px": f.price, "mult": round(f.price / q["entry_px"], 2)})
            if partial:
                q["hit_rec"] = True
            if not partial or q["tokens"] <= q["tokens0"] * 0.01:
                self._close(mint, q, why)

    def reclaim_rent(self, mint: str) -> float:
        """Cierra las cuentas de token vacías de ese mint y recupera la renta (~0,002 SOL = 8% de un ticket de 0,025)."""
        from solders.hash import Hash
        from solders.instruction import AccountMeta, Instruction
        from solders.message import Message
        from solders.pubkey import Pubkey
        from solders.transaction import Transaction
        try:
            res = self.rpc.call("getTokenAccountsByOwner", [self.pub, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "confirmed"}]) or {}
            ixs = []
            owner = Pubkey.from_string(self.pub)
            for acc in res.get("value", []):
                amt = int(acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
                if amt != 0:
                    continue
                prog = Pubkey.from_string(acc["account"]["owner"])
                a = Pubkey.from_string(acc["pubkey"])
                ixs.append(Instruction(prog, bytes([9]), [AccountMeta(a, False, True), AccountMeta(owner, False, True), AccountMeta(owner, True, False)]))
            if not ixs:
                return 0.0
            bh = (self.rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}]) or {})["value"]["blockhash"]
            tx = Transaction([self.kp], Message(ixs, owner), Hash.from_string(bh))
            sig = self.rpc.send_raw(base64.b64encode(bytes(tx)).decode())
            ok = self.rpc.wait_confirmed(sig, timeout=60)
            jl(LOG, {"ts": time.time(), "ev": "rent_reclaim", "mint": mint, "accounts": len(ixs), "sig": sig, "ok": bool(ok)})
            return 0.00203928 * len(ixs) if ok else 0.0
        except Exception as e:  # noqa: BLE001
            jl(LOG, {"ts": time.time(), "ev": "rent_fail", "mint": mint, "err": str(e)[:200]})
            return 0.0

    def _close(self, mint: str, q: dict, why: str) -> None:
        if not why.endswith("_unsellable"):
            q["proceeds_sol"] += self.reclaim_rent(mint)
        pnl = q["proceeds_sol"] - q["cost_sol"]
        row = {**{k: q.get(k) for k in ("ts", "mint", "sym", "name", "cost_sol", "proceeds_sol", "entry_px", "peak_px", "slip_pct",
                                        "age_at_entry_s", "mcap_sol_entry", "hit_rec", "latency_s")},
               "closed_ts": time.time(), "why": why, "pnl_sol": round(pnl, 6), "mult": round(q["proceeds_sol"] / q["cost_sol"], 3) if q["cost_sol"] else None,
               "peak_mult": round(q["peak_px"] / q["entry_px"], 2), "hold_min": round((time.time() - q["ts"]) / 60), "reason": "floor_lottery"}
        jl(CLOSED, row)
        self.pos.pop(mint, None); self.stats["closed"] += 1

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        log.info("billetera %s modo %s ticket %s SOL ratio %s", self.pub, self.mode(), TICKET, RATIO)
        self.sol_price(); self.save()
        for fn in (self.ws_loop, self.eval_loop, self.manage_loop):
            threading.Thread(target=fn, daemon=True).start()
        while True:
            time.sleep(60)


if __name__ == "__main__":
    Floor().run()
