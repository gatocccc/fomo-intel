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

# Mesa principal (DESK_NAME vacío) o una mesa por plan del piloto automático (DESK_NAME=agresivo|equilibrado|tradicional).
NAME = os.getenv("DESK_NAME", "").strip()
log = logging.getLogger("desk" + (f"-{NAME}" if NAME else ""))
if NAME:
    DEC = Path(f"desk/plans/{NAME}")
    ST_DIR = Path(f"state/plan_{NAME}")
    WEB = Path(f"/var/www/autopilot/plans/{NAME}.json")
    SUMMARY = Path(f"state/plan_{NAME}_summary.json")
    WALLET = Path(f"secrets/plan_{NAME}.json")
else:
    DEC = Path("desk/decisions")
    ST_DIR = Path("state/desk")
    WEB = Path("/var/www/fomo/desk.json")
    SUMMARY = Path("state/desk_summary.json")
    WALLET = None
ST_DIR.mkdir(parents=True, exist_ok=True)
JUP_PRICE = "https://api.jup.ag/price/v3"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
# Pierna del radar que usa esta billetera (ver radar.LEGS) y desde cuándo se contabiliza (los dos primeros cortos reales, 29/10).
PERP_LEG = {"lloyd": ("book", "state/desk/radar_pos_book.json"), "lab": ("lab", "state/desk/radar_pos.json")}.get(NAME)
PERPS_SINCE = 1793309000


def T(es: str, en: str) -> str:
    """Textos del registro: castellano en la mesa, inglés en los planes (los ven los usuarios de la app)."""
    return en if NAME else es
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
        self.kp = load_or_create(WALLET or self.env.wallet_file); self.pub = str(self.kp.pubkey())
        self.rpc = Rpc(self.env.rpc_url)
        self.exe = RealExecutor(p, self.kp, self.rpc, self.env.solanatracker_api_key)
        self.pos: dict = jload(ST_DIR / "positions.json", {})
        self.processed: list = jload(ST_DIR / "processed.json", [])
        self.sol_usd = self.st.sol_usd() or 100.0
        self.prices: dict = {}
        self.no_price_since: dict = {}
        self.wallet_sol = self.rpc.sol_balance(self.pub)
        self.jup_key = os.getenv("JUPITER_API_KEY", "")
        self.maybe_start()

    def maybe_start(self):
        """La mesa arranca (fija saldo inicial) recién cuando la billetera tiene fondos."""
        if self.cfg["start_ts"] or self.wallet_sol < 0.05:
            return
        if NAME:
            self.cfg.setdefault("plan", NAME)
            self.cfg["floor_usd"] = round(self.wallet_sol * self.sol_usd * 0.4, 2)   # corta si pierde 60%
            self.cfg["goal_mult"] = 2; self.cfg["days"] = 30
        if not self.cfg["start_ts"]:
            self.cfg.update({"start_ts": time.time(), "start_sol": round(self.wallet_sol, 6), "start_usd": round(self.wallet_sol * self.sol_usd, 2)})
            jsave(ST_DIR / "config.json", self.cfg)
            if NAME:
                self.journal("Plan started", f"Starting balance {self.wallet_sol:.4f} SOL (${self.wallet_sol * self.sol_usd:.2f} at SOL ${self.sol_usd:.2f}). "
                             f"Hard floor: ${self.cfg['floor_usd']:.0f} (stops everything if the plan loses 60%).", kind="system")
                return
            self.journal("Arranque de la mesa", f"Saldo inicial {self.wallet_sol:.4f} SOL (US${self.wallet_sol * self.sol_usd:.2f}, SOL a US${self.sol_usd:.2f}). "
                         f"Objetivo: x{self.cfg['goal_mult']} en {self.cfg['days']} días. Piso de corte: US${self.cfg['floor_usd']:.0f}.", kind="sistema")

    # ---------- registro ----------
    def journal(self, title, text, kind="decisión", did=None):
        append("journal.jsonl", {"ts": time.time(), "title": title, "text": text, "kind": kind, "id": did})

    def save(self):
        jsave(ST_DIR / "positions.json", self.pos); jsave(ST_DIR / "processed.json", self.processed)

    # ---------- precios ----------
    def jup_price(self, mint):
        if not self.jup_key:
            return None
        try:
            import requests
            r = requests.get(JUP_PRICE, params={"ids": mint}, headers={"x-api-key": self.jup_key}, timeout=8)
            d = r.json().get(mint) or {}
            return float(d.get("usdPrice") or 0) or None
        except Exception:  # noqa: BLE001
            return None

    def price_usd(self, mint):
        px = self.jup_price(mint) or self.st.price(mint)
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
                              "tp": o.get("tp", []), "tp_done": [], "thesis": o.get("thesis", ""), "id": did, "sleeve": o.get("sleeve"), "reason": o.get("reason"),
                              "max_h": o.get("max_h")}
        self.save()
        return T(f"compró {f.tokens:,.0f} {o.get('symbol')} por {f.sol:.4f} SOL a US${entry_usd:.6g} (slippage {f.slippage_pct:+.1f}%)", f"bought {f.tokens:,.0f} {o.get('symbol')} for {f.sol:.4f} SOL at ${entry_usd:.6g} (slippage {f.slippage_pct:+.1f}%)")

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
                   "peak_mult": round(p["peak_usd"] / p["entry_usd"], 2), "hold_h": round((time.time() - p["opened_ts"]) / 3600, 1), "why": why,
                   "reason": p.get("reason"), "sleeve": p.get("sleeve")}
            append("closed.jsonl", row); self.pos.pop(mint, None)
        self.save()
        return T(f"vendió {frac:.0%} de {p['symbol']} ({why}) por {f.sol:.4f} SOL" + (" — posición cerrada" if closed else ""), f"sold {frac:.0%} of {p['symbol']} ({why}) for {f.sol:.4f} SOL" + (" — position closed" if closed else ""))

    def writeoff(self, mint, why, did=None):
        """30/10: da de baja una posición en un token muerto (sin liquidez, la venta falla y Jupiter cotiza ~0). Antes SAFU seguía en el
        lab valuado al precio de entrada (~US$5) por horas: el patrimonio público mentía. Cierra a valor 0; los tokens quedan en la billetera."""
        p = self.pos.get(mint)
        if not p:
            return "sin posición"
        pnl_sol = p["sol_out"] - p["sol_in"]
        append("trades.jsonl", {"ts": time.time(), "side": "writeoff", "mint": mint, "symbol": p["symbol"], "ok": True, "sol": 0.0, "tokens": p["tokens"],
                                "price_usd": 0.0, "why": why, "sig": None, "error": "", "id": did})
        append("closed.jsonl", {"ts": time.time(), "mint": mint, "symbol": p["symbol"], "sol_in": round(p["sol_in"], 5), "sol_out": round(p["sol_out"], 5),
                                "pnl_sol": round(pnl_sol, 5), "pnl_usd": round(pnl_sol * self.sol_usd, 2), "ret": round(p["sol_out"] / p["sol_in"] - 1, 3) if p["sol_in"] else None,
                                "peak_mult": round(p["peak_usd"] / p["entry_usd"], 2), "hold_h": round((time.time() - p["opened_ts"]) / 3600, 1), "why": why,
                                "reason": p.get("reason"), "sleeve": p.get("sleeve")})
        self.pos.pop(mint, None); self.save()
        return T(f"dio de baja {p['symbol']} a valor 0 ({why})", f"wrote off {p['symbol']} at zero ({why})")

    def apply_decisions(self):
        # decisiones de Claude (repo) y del cerebro automático (state/<mesa>/auto, ver brain.py)
        files = sorted(DEC.glob("*.json")) if DEC.exists() else []
        files += sorted((ST_DIR / "auto").glob("*.json")) if (ST_DIR / "auto").exists() else []
        for fp in files:
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
                            for k in ("stop", "trail", "trail_after", "tp", "thesis", "brain", "sleeve", "reason", "max_h"):
                                if k in o: p[k] = o[k]
                            self.save(); r = f"ajustó {p['symbol']}: " + ", ".join(f"{k}={o[k]}" for k in o if k not in ("action", "mint"))
                        else: r = "sin posición"
                    elif a == "writeoff": r = self.writeoff(o["mint"], o.get("why", "token muerto"), did)
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
                self.journal(T("Ejecución", "Execution"), "\n".join(results), kind=T("ejecución", "execution"), did=did)

    # ---------- protección ----------
    def protect(self):
        for mint, p in list(self.pos.items()):
            px = self.price_usd(mint)
            if not px:
                # 30/10: sin precio igual vale el tope de tiempo (SAFU en el lab llevaba horas "sin precio" y el max_h nunca iba a disparar)
                if p.get("max_h") and time.time() - p["opened_ts"] > float(p["max_h"]) * 3600 and not p.get("_tstop_tried"):
                    p["_tstop_tried"] = True
                    r = self.sell(mint, 1.0, T(f"tiempo máximo ({p['max_h']} h, sin precio)", f"time stop ({p['max_h']}h, no price feed)"))
                    self.journal(T("Salida automática", "Automatic exit"), f"{p['symbol']}: {r}", kind=T("automático", "automatic")); continue
                if time.time() - self.no_price_since.get(mint, time.time()) > 600 and not p.get("_warned"):
                    p["_warned"] = True; self.journal(T("Alerta", "Alert"), T(f"{p['symbol']}: sin precio hace más de 10 min", f"{p['symbol']}: no price for over 10 minutes"), kind=T("alerta", "alert"))
                continue
            p["peak_usd"] = max(p["peak_usd"], px); p["last_usd"] = px
            m = px / p["entry_usd"]
            why = None
            if m <= 1 - p["stop"]:
                why = f"stop ({m:.2f}x)"
            elif p.get("max_h") and time.time() - p["opened_ts"] > float(p["max_h"]) * 3600:
                why = T(f"tiempo máximo ({p['max_h']} h, {m:.2f}x)", f"time stop ({p['max_h']}h, {m:.2f}x)")
            elif p["peak_usd"] >= p["entry_usd"] * p["trail_after"] and px <= p["peak_usd"] * (1 - p["trail"]):
                why = T(f"trailing ({m:.2f}x, pico {p['peak_usd'] / p['entry_usd']:.2f}x)", f"trailing stop ({m:.2f}x, peak {p['peak_usd'] / p['entry_usd']:.2f}x)")
            if why:
                r = self.sell(mint, 1.0, why); self.journal(T("Salida automática", "Automatic exit"), f"{p['symbol']}: {r}", kind=T("automático", "automatic")); continue
            for mult, frac in p.get("tp", []):
                key = f"{mult}"
                if key not in p["tp_done"] and m >= mult:
                    p["tp_done"].append(key); self.save()
                    r = self.sell(mint, float(frac), T(f"toma de ganancia {mult}x", f"take profit at {mult}x"))
                    self.journal(T("Toma de ganancia", "Profit taken"), f"{p['symbol']}: {r}", kind=T("automático", "automatic"))
                    break

    def perps_sync(self):
        """Cortos del radar (fomo-radar) pagados con el USDC de esta billetera. El colateral sale del USDC on-chain, pero el libro lo
        sigue contando como USDC (no cambia el patrimonio mientras está abierto). Lo que faltaba (30/10): sumar el resultado del corto.
        - abierto: la ganancia/pérdida no realizada se suma al patrimonio (no se toca book.json);
        - cerrado: el colateral vuelve como USDC con la ganancia o la pérdida → se ajustan los tokens de USDC del libro una sola vez."""
        if not PERP_LEG:
            return 0.0
        leg, pos_file = PERP_LEG
        applied_f = ST_DIR / "perps_applied.json"
        applied = set(jload(applied_f, []))
        try:
            rows = [json.loads(l) for l in Path("state/desk/radar_closed.jsonl").read_text().splitlines() if l.strip()]
        except Exception:  # noqa: BLE001
            rows = []
        changed = False
        for r in rows:
            key = f"{r.get('ts_open')}"
            if r.get("leg", "lab") != leg or r.get("mode") != "live" or (r.get("ts_open") or 0) < PERPS_SINCE or key in applied:
                continue
            applied.add(key); changed = True
            u = self.pos.get(USDC_MINT)
            pnl = float(r.get("pnl_usd") or 0.0)
            if u:
                u["tokens"] = max(0.0, u["tokens"] + pnl / (u.get("last_usd") or 1.0)); self.save()
            self.journal(T("Corto de SOL cerrado", "SOL short settled"),
                         T(f"El corto de SOL del radar volvió a la billetera como USDC: resultado US${pnl:+.2f} ({r.get('why')}). El saldo de USDC del libro quedó ajustado.",
                           f"The radar's SOL short settled back into USDC: result ${pnl:+.2f} ({r.get('why')}). The book's USDC balance was adjusted accordingly."),
                         kind=T("automático", "automatic"))
        if changed:
            jsave(applied_f, sorted(applied))
        # 30/10 (tarde): el resultado no realizado de las perps abiertas se suma UNA sola vez, en `perps_positions()` (radar + tortuga
        # + tendencia del lab). Antes se sumaba acá (estimado) y otra vez en `publish` (radar.json): el corto del radar contaba doble.
        return 0.0

    def equity(self):
        try:
            self.wallet_sol = self.rpc.sol_balance(self.pub)
        except Exception:  # noqa: BLE001
            pass
        pos_usd = sum(p["tokens"] * (self.prices.get(m) or p.get("last_usd") or p["entry_usd"]) for m, p in self.pos.items())
        try:
            self.perps_sync()                                             # liquida en USDC los cierres de perps (una sola vez cada uno)
            pos_usd += sum(x["pnl_usd"] for x in self.perps_positions())  # resultado no realizado de las perps abiertas (radar, tortuga, tendencia)
        except Exception as e:  # noqa: BLE001
            log.warning("perps_sync: %s", e)
        return self.wallet_sol * self.sol_usd + pos_usd, pos_usd

    def floor_check(self, eq):
        if eq < self.cfg["floor_usd"] and not (ST_DIR / "HALT").exists():
            (ST_DIR / "HALT").write_text(f"patrimonio US${eq:.2f} bajo el piso")
            for m in list(self.pos):
                self.sell(m, 1.0, "piso de patrimonio")
            self.journal(T("Mesa detenida", "Plan stopped"), T(f"El patrimonio cayó a US${eq:.2f}, debajo del piso de US${self.cfg['floor_usd']:.0f}. Vendí todo y no opero más sin tu OK.", f"Balance fell to ${eq:.2f}, below the ${self.cfg['floor_usd']:.0f} floor. Everything was sold and the plan is stopped."), kind=T("sistema", "system"))

    def perps_positions(self):
        """Cortos abiertos por el radar (fomo_intel/desk/radar.py) en la billetera de ESTA mesa, como posiciones para la página y el cerebro.
        El colateral ya está contado en la posición de USDC (salió de la billetera sin que el motor lo sepa): acá se muestra el corto con
        colateral + resultado y se descuenta el colateral del USDC. `brain: False` para que el cerebro no intente venderlo ni moverle el stop."""
        r = jload(Path("state/desk/radar.json"), {}) or {}
        out = []
        for leg, p in (r.get("positions") or {}).items():
            if not p or p.get("mode") != "live":
                continue
            plan = p.get("plan") or {"lab": "lab", "book": "lloyd"}.get(leg)
            if (plan or "") != (NAME or ""):
                continue
            coll = float(p.get("collateral_usd") or 0); size = float(p.get("size_usd") or 0); ret = float(p.get("ret_px") or 0)
            pnl = round(ret * size, 2)
            out.append({"mint": f"perps:{p.get('pubkey') or leg}", "symbol": f"SOL short {p.get('lev', 2):g}x", "opened_ts": p["ts"], "entry_usd": p["entry"],
                        "last_usd": p.get("mark") or p["entry"], "peak_usd": p["entry"] * (1 - float(p.get("best_ret") or 0)), "tokens": 0, "tokens_initial": 0,
                        "sol_in": round(coll / self.sol_usd, 4), "sol_out": 0.0, "stop": 0.035, "trail": 0.02, "trail_after": 1.04, "tp": [], "tp_done": [],
                        "thesis": T(f"Corto de SOL por shock de noticias (radar). Colateral US${coll:.0f} a {p.get('lev', 2):g}x; stop si SOL sube 3,5%; trailing 2% desde el mejor punto una vez que gana 4%.",
                                    f"News-shock SOL short (radar). ${coll:.0f} collateral at {p.get('lev', 2):g}x; stop if SOL rises 3.5%; trails 2% from its best once up 4%."),
                        "id": f"radar-{leg}", "sleeve": "majors", "reason": "news_shock_short", "brain": False, "perps": True, "system": "News-shock short",
                        "mult": round(1 + ret * float(p.get("lev") or 2), 3), "value_usd": round(coll + pnl, 2), "pnl_usd": pnl, "collateral_usd": coll, "side": "short"})
        # 30/10 (tarde): la tortuga 55/20 del libro (dict moneda → posición) y la tendencia diaria del lab (una posición) también son perps
        # de ESTA billetera. Antes no se listaban: /book/ decía "1 open" con dos cortos abiertos y el bolsillo de majors no las contaba.
        f = {"lloyd": "state/desk/turtle_pos_book.json", "lab": "state/desk/trend_pos_lab.json"}.get(NAME or "")
        obj = jload(Path(f), None) if f else None
        items = [obj] if (obj and "ts" in obj) else list((obj or {}).values())
        for p in items:
            if not p or p.get("mode") != "live" or not p.get("pubkey"):
                continue
            coin = p.get("symbol") or p.get("coin") or "?"; side = p.get("side") or "short"; d = 1 if side == "long" else -1
            coll = float(p.get("collateral_usd") or 0); size = float(p.get("size_usd") or coll * float(p.get("lev") or 2)); ret = float(p.get("ret_px") or 0)
            pnl = round(ret * size, 2); lev = float(p.get("lev") or 2); ex = p.get("exit_level") or p.get("stop_px")
            stop = round(abs(float(ex) / float(p["entry"]) - 1), 4) if ex and p.get("entry") else None
            turtle = (p.get("system") or "").startswith("turtle") or "exit_level" in p
            thesis = (T(f"Tortuga 55/20: {coin} tocó su {'máximo' if d > 0 else 'mínimo'} de 55 días. {side} a {lev:g}x, colateral US${coll:.0f}; sale al tocar el {'mínimo' if d > 0 else 'máximo'} de 20 días (US${float(ex):,.2f}), riesgo 1% del libro.",
                        f"Breakout 55/20: {coin} touched its 55-day {'high' if d > 0 else 'low'}. {side} at {lev:g}x, ${coll:.0f} collateral; exits when it touches the 20-day {'low' if d > 0 else 'high'} (${float(ex):,.2f}), 1% of the book at risk.") if (turtle and ex)
                      else T(f"Tendencia diaria en majors: {side} {coin} a {lev:g}x, colateral US${coll:.0f}.", f"Daily trend on majors: {side} {coin} at {lev:g}x, ${coll:.0f} collateral."))
            out.append({"mint": f"perps:{p.get('pubkey')}", "symbol": f"{coin} {side} {lev:g}x", "opened_ts": p["ts"], "entry_usd": p["entry"],
                        "last_usd": p.get("mark") or p["entry"], "peak_usd": p["entry"], "tokens": 0, "tokens_initial": 0,
                        "sol_in": round(coll / self.sol_usd, 4), "sol_out": 0.0, "stop": stop, "trail": None, "trail_after": None, "tp": [], "tp_done": [],
                        "thesis": thesis, "id": f"{'turtle' if turtle else 'trend'}-{coin}", "sleeve": "majors", "reason": "majors_trend", "brain": False, "perps": True,
                        "system": "Breakout 55/20" if turtle else "Daily trend", "exit_level": ex,
                        "mult": round(1 + ret * lev, 3), "value_usd": round(coll + pnl, 2), "pnl_usd": pnl, "collateral_usd": coll, "side": side})
        return out

    def publish(self, eq, pos_usd):
        c = self.cfg; now = time.time()
        if not c["start_ts"]:
            s = {"now": now, "plan": NAME or None, "wallet": self.pub, "started": False, "cash_sol": round(self.wallet_sol, 4), "sol_usd": round(self.sol_usd, 2)}
            jsave(SUMMARY, s)
            try:
                if NAME: WEB.parent.mkdir(parents=True, exist_ok=True); jsave(WEB, s)
            except Exception:  # noqa: BLE001
                pass
            return
        hist = tail("equity.jsonl", 3000)
        closed = tail("closed.jsonl", 200)
        perps = self.perps_positions()
        perps_pnl = sum(x["pnl_usd"] for x in perps); perps_coll = sum(x["collateral_usd"] for x in perps)   # ya incluido en eq (equity())
        s = {"now": now, "start_ts": c["start_ts"], "start_usd": c["start_usd"], "start_sol": c["start_sol"], "goal_usd": round(c["start_usd"] * c["goal_mult"], 2),
             "days": c["days"], "day": int((now - c["start_ts"]) // 86400) + 1, "equity_usd": round(eq, 2), "equity_sol": round(eq / self.sol_usd, 4),
             "cash_sol": round(self.wallet_sol, 4), "positions_usd": round(pos_usd, 2), "sol_usd": round(self.sol_usd, 2),
             "mult": round(eq / c["start_usd"], 3) if c["start_usd"] else None, "halt": (ST_DIR / "HALT").exists(), "pause": (ST_DIR / "PAUSE").exists(),
             "positions": [{k: v for k, v in p.items() if not k.startswith("_")} | {"mult": round((p.get("last_usd") or p["entry_usd"]) / p["entry_usd"], 3),
                            "value_usd": round(p["tokens"] * (p.get("last_usd") or p["entry_usd"]) - (perps_coll if p["mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" else 0), 2)}
                           for p in self.pos.values()] + perps,
             "perps_pnl_usd": round(perps_pnl, 2),
             "equity": [[round(h["ts"]), h["usd"]] for h in hist],
             "closed": closed[::-1][:50], "trades": tail("trades.jsonl", 60)[::-1], "journal": tail("journal.jsonl", 200)[::-1],
             "wins": sum(1 for r in closed if (r.get("pnl_usd") or 0) > 0), "n_closed": len(closed), "realized_usd": round(sum(r.get("pnl_usd") or 0 for r in closed), 2)}
        s["plan"] = NAME or None; s["wallet"] = self.pub
        b = jload(ST_DIR / "brain.json", {}); rg = jload(Path("state/desk/regime.json"), {})
        if b:
            s["brain"] = {k: b.get(k) for k in ("mode", "last_run", "regime", "status", "last_action", "last_note", "trad_status")} | {"sol_ch24h": rg.get("sol_ch24h"), "sol_vs_ma20": round(rg["sol"] / rg["sol_ma20"] - 1, 4) if rg.get("sol_ma20") else None}
        jsave(SUMMARY, s)
        try:
            if NAME: WEB.parent.mkdir(parents=True, exist_ok=True)
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
                    self.maybe_start()
                    if self.cfg["start_ts"]:
                        self.floor_check(eq)
                    if now - last_eq > 300 and self.cfg["start_ts"]:
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
