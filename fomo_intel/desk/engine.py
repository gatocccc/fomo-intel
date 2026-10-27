"""Mesa autónoma (desde 27/10/2026). Claude decide; este motor ejecuta y protege 24/7.

- Decisiones: archivos JSON en el repo `desk/decisions/*.json` (llegan al servidor por la sincronización de GitHub).
  {"id": "...", "journal": "razonamiento", "orders": [
      {"action": "buy", "mint": "...", "symbol": "X", "sol": 0.3, "stop": 0.3, "trail": 0.35, "trail_after": 1.5,
       "tp": [[3, 0.33], [6, 0.33]], "thesis": "..."},
      {"action": "sell", "mint": "...", "frac": 1.0, "why": "..."},
      {"action": "set", "mint": "...", "stop": 0.25, "trail": 0.3, "trail_after": 1.3, "tp": [[2, 0.5]]}]}
  Cada decisión se ejecuta UNA sola vez (state/desk/processed.json).
- Protección cada 15 s: stop desde la entrada, trailing desde el pico (activo después de `trail_after`x), escalera de ventas.
- Piso: si el patrimonio cae debajo de `floor_usd`, vende todo y se detiene (state/desk/HALT).
- Publica state/desk_summary.json y /var/www/fomo/desk.json para la página.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from ..live.config import Env, LiveParams
from ..live.executor import RealExecutor
from ..live.signals import STClient
from ..live.wallet import Rpc, load_or_create

log = logging.getLogger("desk")
DEC = Path("desk/decisions")
ST_DIR = Path("state/desk"); ST_DIR.mkdir(parents=True, exist_ok=True)
WEB = Path("/var/www/fomo/desk.json")
CFG_DEFAULT = {"start_ts": None, "start_usd": None, "start_sol": None, "goal_mult": 10, "days": 14, "floor_usd": 15.0,
               "reserve_sol": 0.03, "max_slippage_pct": 8.0, "swap_slippage_pct": 12.0, "priority_fee_sol": 0.001}


def jload(p, default):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return default


def jsave(p, obj):
    p = Path(p); tmp = p.with_suffix(p.suffix + ".tmp")
    json.dump(obj, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def append(name, row):
    with open(ST_DIR / name, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def tail(name, n=300):
    f = ST_DIR / name
    if not f.exists():
        return []
    out = []
    for l in f.read_text().splitlines()[-n:]:
        try: out.append(json.loads(l))
        except Exception: pass  # noqa: BLE001
    return out


class Desk:
    def __init__(self):
        self.env = Env()
        self.cfg = {**CFG_DEFAULT, **jload(ST_DIR / "config.json", {})}
        self.st = STClient(self.env.solanatracker_api_key)
        p = LiveParams(); p.max_slippage_pct = self.cfg["max_slippage_pct"]; p.swap_slippage_pct = self.cfg["swap_slippage_pct"]
        p.priority_fee_sol = self.cfg["priority_fee_sol"]; p.min_sol_reserve = self.cfg["reserve_sol"]
        self.kp = load_or_create(self.env.wallet_file); self.pub = str(self.kp.pubkey())
        self.rpc = Rpc(self.env.rpc_url)
        self.exe = RealExecutor(p, self.kp, self.rpc, self.env.solanatracker_api_key)
        self.pos: dict = jload(ST_DIR / "positions.json", {})
        self.processed: list = jload(ST_DIR / "processed.json", [])
        self.sol_usd = self.st.sol_usd() or 100.0
        self.prices: dict = {}
        self.no_price_since: dict = {}
        self.wallet_sol = self.rpc.sol_balance(self.pub)
        if not self.cfg["start_ts"]:
            self.cfg.update({"start_ts": time.time(), "start_sol": round(self.wallet_sol, 6), "start_usd": round(self.wallet_sol * self.sol_usd, 2)})
            jsave(ST_DIR / "config.json", self.cfg)
            self.journal("Arranque de la mesa", f"Saldo inicial {self.wallet_sol:.4f} SOL (US${self.wallet_sol * self.sol_usd:.2f}, SOL a US${self.sol_usd:.2f}). "
                         f"Objetivo: x{self.cfg['goal_mult']} en {self.cfg['days']} días. Piso de corte: US${self.cfg['floor_usd']:.0f}.", kind="sistema")

    # ---------- registro ----------
    def journal(self, title, text, kind="decisión", did=None):
        append("journal.jsonl", {"ts": time.time(), "title": title, "text": text, "kind": kind, "id": did})

    def save(self):
        jsave(ST_DIR / "positions.json", self.pos); jsave(ST_DIR / "processed.json", self.processed)

    # ---------- precios ----------
    def price_usd(self, mint):
        px = self.st.price(mint)
        if px:
            self.prices[mint] = px; self.no_price_since.pop(mint, None)
        else:
            self.no_price_since.setdefault(mint, time.time())
        return px or self.prices.get(mint)

    # ---------- órdenes ----------
    def buy(self, o, did):
        mint, sol = o["mint"], float(o["sol"])
        if (ST_DIR / "HALT").exists():
            return "mesa detenida (HALT)"
        if (ST_DIR / "PAUSE").exists():
            return "mesa en pausa: no compra"
        bal = self.rpc.sol_balance(self.pub)
        if bal - sol < self.cfg["reserve_sol"]:
            sol = round(bal - self.cfg["reserve_sol"] - 0.005, 4)
            if sol < 0.02:
                return f"sin saldo ({bal:.4f} SOL)"
        px = self.price_usd(mint)
        if not px:
            return "sin precio"
        f = self.exe.buy(mint, sol, px / self.sol_usd)
        append("trades.jsonl", {"ts": time.time(), "side": "buy", "mint": mint, "symbol": o.get("symbol"), "ok": f.ok, "sol": f.sol, "tokens": f.tokens,
                                "price_usd": round(f.price * self.sol_usd, 12) if f.ok else None, "slip": f.slippage_pct, "sig": f.sig, "error": f.error[:200], "id": did})
        if not f.ok:
            return f"compra falló: {f.error[:120]}"
        cur = self.pos.get(mint)
        entry_usd = f.price * self.sol_usd
        if cur:      # promedio
            tok = cur["tokens"] + f.tokens
            cur["entry_usd"] = (cur["entry_usd"] * cur["tokens"] + entry_usd * f.tokens) / tok
            cur["tokens"] = tok; cur["tokens_initial"] += f.tokens; cur["sol_in"] += f.sol
        else:
            self.pos[mint] = {"mint": mint, "symbol": o.get("symbol") or mint[:6], "opened_ts": time.time(), "entry_usd": entry_usd,
                              "tokens": f.tokens, "tokens_initial": f.tokens, "sol_in": f.sol, "sol_out": 0.0, "peak_usd": entry_usd,
                              "stop": float(o.get("stop", 0.3)), "trail": float(o.get("trail", 0.35)), "trail_after": float(o.get("trail_after", 1.5)),
                              "tp": o.get("tp", []), "tp_done": [], "thesis": o.get("thesis", ""), "id": did}
        self.save()
        return f"compró {f.tokens:,.0f} {o.get('symbol')} por {f.sol:.4f} SOL a US${entry_usd:.6g} (slippage {f.slippage_pct:+.1f}%)"

    def sell(self, mint, frac, why, did=None):
        p = self.pos.get(mint)
        if not p:
            return "sin posición"
        tokens = p["tokens"] if frac >= 0.999 else min(p["tokens"], p["tokens_initial"] * frac)
        px = self.price_usd(mint) or self.prices.get(mint) or p["entry_usd"]
        f = None
        for i in range(3):
            f = self.exe.sell(mint, tokens, px / self.sol_usd, fast=i == 2)
            if f.ok or "sin tokens" in f.error:
                break
            time.sleep(3)
        append("trades.jsonl", {"ts": time.time(), "side": "sell", "mint": mint, "symbol": p["symbol"], "ok": f.ok, "sol": f.sol, "tokens": f.tokens,
                                "price_usd": round(f.price * self.sol_usd, 12) if f.ok else None, "why": why, "sig": f.sig, "error": f.error[:200], "id": did})
        if not f.ok and "sin tokens" not in f.error:
            return f"venta falló: {f.error[:120]}"
        p["tokens"] = max(0.0, p["tokens"] - (f.tokens if f.ok else p["tokens"]))
        p["sol_out"] += f.sol if f.ok else 0.0
        closed = p["tokens"] <= p["tokens_initial"] * 0.002
        if closed:
            pnl_sol = p["sol_out"] - p["sol_in"]
            row = {"ts": time.time(), "mint": mint, "symbol": p["symbol"], "sol_in": round(p["sol_in"], 5), "sol_out": round(p["sol_out"], 5),
                   "pnl_sol": round(pnl_sol, 5), "pnl_usd": round(pnl_sol * self.sol_usd, 2), "ret": round(p["sol_out"] / p["sol_in"] - 1, 3) if p["sol_in"] else None,
                   "peak_mult": round(p["peak_usd"] / p["entry_usd"], 2), "hold_h": round((time.time() - p["opened_ts"]) / 3600, 1), "why": why}
            append("closed.jsonl", row); self.pos.pop(mint, None)
        self.save()
        return f"vendió {frac:.0%} de {p['symbol']} ({why}) por {f.sol:.4f} SOL" + (" — posición cerrada" if closed else "")

    def apply_decisions(self):
        if not DEC.exists():
            return
        for fp in sorted(DEC.glob("*.json")):
            try:
                d = json.load(open(fp))
            except Exception as e:  # noqa: BLE001
                log.warning("decisión ilegible %s: %s", fp, e); continue
            did = d.get("id") or fp.stem
            if did in self.processed:
                continue
            self.processed.append(did); self.save()          # antes de ejecutar: nunca dos veces
            results = []
            for o in d.get("orders", []):
                try:
                    a = o.get("action")
                    if a == "buy": r = self.buy(o, did)
                    elif a == "sell": r = self.sell(o["mint"], float(o.get("frac", 1.0)), o.get("why", "decisión"), did)
                    elif a == "set":
                        p = self.pos.get(o["mint"])
                        if p:
                            for k in ("stop", "trail", "trail_after", "tp", "thesis"):
                                if k in o: p[k] = o[k]
                            self.save(); r = f"ajustó {p['symbol']}: " + ", ".join(f"{k}={o[k]}" for k in o if k not in ("action", "mint"))
                        else: r = "sin posición"
                    elif a == "pause": (ST_DIR / "PAUSE").write_text(o.get("why", "")); r = "pausa"
                    elif a == "resume":
                        if (ST_DIR / "PAUSE").exists(): (ST_DIR / "PAUSE").unlink()
                        r = "reanuda"
                    else: r = f"acción desconocida {a}"
                except Exception as e:  # noqa: BLE001
                    r = f"error: {str(e)[:150]}"
                results.append(f"{o.get('action')} {o.get('symbol') or o.get('mint', '')[:6]}: {r}")
                log.info("decisión %s -> %s", did, results[-1])
            self.journal(d.get("title") or "Decisión", d.get("journal", ""), kind="decisión", did=did)
            if results:
                self.journal("Ejecución", "\n".join(results), kind="ejecución", did=did)

    # ---------- protección ----------
    def protect(self):
        for mint, p in list(self.pos.items()):
            px = self.price_usd(mint)
            if not px:
                if time.time() - self.no_price_since.get(mint, time.time()) > 600 and not p.get("_warned"):
                    p["_warned"] = True; self.journal("Alerta", f"{p['symbol']}: sin precio hace más de 10 min", kind="alerta")
                continue
            p["peak_usd"] = max(p["peak_usd"], px); p["last_usd"] = px
            m = px / p["entry_usd"]
            why = None
            if m <= 1 - p["stop"]:
                why = f"stop ({m:.2f}x)"
            elif p["peak_usd"] >= p["entry_usd"] * p["trail_after"] and px <= p["peak_usd"] * (1 - p["trail"]):
                why = f"trailing ({m:.2f}x, pico {p['peak_usd'] / p['entry_usd']:.2f}x)"
            if why:
                r = self.sell(mint, 1.0, why); self.journal("Salida automática", f"{p['symbol']}: {r}", kind="automático"); continue
            for mult, frac in p.get("tp", []):
                key = f"{mult}"
                if key not in p["tp_done"] and m >= mult:
                    p["tp_done"].append(key); self.save()
                    r = self.sell(mint, float(frac), f"toma de ganancia {mult}x")
                    self.journal("Toma de ganancia", f"{p['symbol']}: {r}", kind="automático")
                    break

    def equity(self):
        try:
            self.wallet_sol = self.rpc.sol_balance(self.pub)
        except Exception:  # noqa: BLE001
            pass
        pos_usd = sum(p["tokens"] * (self.prices.get(m) or p.get("last_usd") or p["entry_usd"]) for m, p in self.pos.items())
        return self.wallet_sol * self.sol_usd + pos_usd, pos_usd

    def floor_check(self, eq):
        if eq < self.cfg["floor_usd"] and not (ST_DIR / "HALT").exists():
            (ST_DIR / "HALT").write_text(f"patrimonio US${eq:.2f} bajo el piso")
            for m in list(self.pos):
                self.sell(m, 1.0, "piso de patrimonio")
            self.journal("Mesa detenida", f"El patrimonio cayó a US${eq:.2f}, debajo del piso de US${self.cfg['floor_usd']:.0f}. Vendí todo y no opero más sin tu OK.", kind="sistema")

    def publish(self, eq, pos_usd):
        c = self.cfg; now = time.time()
        hist = tail("equity.jsonl", 3000)
        closed = tail("closed.jsonl", 200)
        s = {"now": now, "start_ts": c["start_ts"], "start_usd": c["start_usd"], "start_sol": c["start_sol"], "goal_usd": round(c["start_usd"] * c["goal_mult"], 2),
             "days": c["days"], "day": int((now - c["start_ts"]) // 86400) + 1, "equity_usd": round(eq, 2), "equity_sol": round(eq / self.sol_usd, 4),
             "cash_sol": round(self.wallet_sol, 4), "positions_usd": round(pos_usd, 2), "sol_usd": round(self.sol_usd, 2),
             "mult": round(eq / c["start_usd"], 3) if c["start_usd"] else None, "halt": (ST_DIR / "HALT").exists(), "pause": (ST_DIR / "PAUSE").exists(),
             "positions": [{k: v for k, v in p.items() if not k.startswith("_")} | {"mult": round((p.get("last_usd") or p["entry_usd"]) / p["entry_usd"], 3),
                            "value_usd": round(p["tokens"] * (p.get("last_usd") or p["entry_usd"]), 2)} for p in self.pos.values()],
             "equity": [[round(h["ts"]), h["usd"]] for h in hist],
             "closed": closed[::-1][:50], "trades": tail("trades.jsonl", 60)[::-1], "journal": tail("journal.jsonl", 200)[::-1],
             "wins": sum(1 for r in closed if (r.get("pnl_usd") or 0) > 0), "n_closed": len(closed), "realized_usd": round(sum(r.get("pnl_usd") or 0 for r in closed), 2)}
        jsave("state/desk_summary.json", s)
        try:
            if WEB.parent.exists(): jsave(WEB, s)
        except Exception:  # noqa: BLE001
            pass

    def run(self):
        last_eq = last_pub = last_sol = 0.0
        while True:
            now = time.time()
            try:
                if now - last_sol > 120:
                    self.sol_usd = self.st.sol_usd(60) or self.sol_usd; last_sol = now
                    nc = {**CFG_DEFAULT, **jload(ST_DIR / "config.json", {})}; self.cfg.update({k: nc[k] for k in ("floor_usd", "goal_mult", "days")})
                self.apply_decisions()
                if not (ST_DIR / "HALT").exists():
                    self.protect()
                if now - last_pub > 30:
                    eq, pos_usd = self.equity(); last_pub = now
                    self.floor_check(eq)
                    if now - last_eq > 300:
                        append("equity.jsonl", {"ts": now, "usd": round(eq, 2), "sol": round(eq / self.sol_usd, 4), "sol_usd": round(self.sol_usd, 2)}); last_eq = now
                    self.publish(eq, pos_usd)
            except Exception as e:  # noqa: BLE001
                log.exception("error en el ciclo: %s", e)
            time.sleep(15)


def main():
    from ..live.bot import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Desk().run()


if __name__ == "__main__":
    main()
