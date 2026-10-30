"""Tortuga 55/20 en majors con órdenes por nivel — libro Lloyd, en real (30/10/2026).

Pedido de Gastón (30/10): "tener guardados puntos que, cuando los toquen ciertas coins, disparen compras automáticas, y puntos
que disparen ventas automáticas; estar siempre activos sea cual sea el mercado".

Evidencia (backtest del 30/10, 8 mercados, Binance diario 2020–26, comisión 0,1% por lado + 0,2% de slippage + funding 10%/año
para largos; diseño 2020–23, prueba 2024–26):
- Tortuga 55/20 (Richard Dennis, "Sistema 2", sin optimizar): entra cuando el precio TOCA el máximo de 55 días (largo) o el mínimo de
  55 días (corto) y sale cuando toca el mínimo / máximo de 20 días.
  · solo largo: prueba 82 operaciones, 43% de aciertos, +13,8% medio por operación, t 2,35; positivo en 7 de 8 mercados.
  · largo y corto: prueba 148 operaciones, 45% de aciertos, +7,1% medio por operación, t 2,04; 7 de 8 mercados.
  · entradas al azar con la misma salida: +1,8% (p50) / +4,3% (p95) → la tortuga les gana.
- La tortuga 20/10 y la 10/5 (más rápidas) dan menos (t 1,8 y 1,2 en largos). Las grillas de 2% y las señales de horas pierden.
Pierde muchas veces (55–65% de las operaciones) y gana poco seguido pero grande: el tamaño es lo que la hace sobrevivible.

Reglas (en BTC, ETH y SOL, que es lo que ofrece Jupiter Perps):
- Niveles: se recalculan con cada cierre diario de Hyperliquid (velas cerradas). Se publican en state/desk/levels.json.
- Entrada: el precio toca el nivel. Si al ver el toque ya pasó más de 1% el nivel (hueco), no se persigue.
- Salida: el precio toca el nivel de salida (mínimo de 20 días para largos, máximo de 20 días para cortos). Ese nivel es el stop.
- Tamaño: pérdida hasta la salida = 1% del libro; apalancamiento 2x; colateral ≤ 8% del libro; mínimo US$10 (si el mínimo
  implica arriesgar más de 2% del libro, no se entra). Máximo una posición por moneda (riesgo total ≤ 3%).
- Si el radar tiene abierto un corto de SOL en el libro, la tortuga no abre otro corto de SOL.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger("turtle")
HL = "https://api.hyperliquid.xyz/info"
ST = Path("state/desk")
POS = ST / "turtle_pos_book.json"      # {coin: posición}
LEVELS = ST / "levels.json"
CLOSED = ST / "radar_closed.jsonl"
COINS = ("BTC", "ETH", "SOL")
R = {"n_in": 55, "n_out": 20, "risk": 0.01, "risk_max": 0.02, "lev": 2.0, "coll_max_frac": 0.08, "coll_min": 10.0, "chase": 0.01}


def jload(p, d):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def jsave(p, o):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp"); json.dump(o, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def levels_for(coin):
    end = int(time.time() * 1000)
    r = requests.post(HL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": end - 80 * 86400000, "endTime": end}}, timeout=20)
    today = int(time.time() // 86400) * 86400
    rows = [(float(c["h"]), float(c["l"])) for c in (r.json() if r.ok else []) if int(c["t"]) // 1000 < today]
    if len(rows) < R["n_in"]:
        return None
    hi_in = max(h for h, _ in rows[-R["n_in"]:]); lo_in = min(l for _, l in rows[-R["n_in"]:])
    hi_out = max(h for h, _ in rows[-R["n_out"]:]); lo_out = min(l for _, l in rows[-R["n_out"]:])
    return {"buy_above": hi_in, "short_below": lo_in, "long_exit_below": lo_out, "short_exit_above": hi_out, "day": today}


class TurtleBook:
    def __init__(self, radar):
        self.radar = radar
        self.leg = next(l for l in radar.legs if l["name"] == "book")
        self.mode = os.getenv("BOOK_TURTLE", "live")
        self.pos = jload(POS, {})
        self.lv = jload(LEVELS, {}).get("levels", {})
        self.lv_day = jload(LEVELS, {}).get("day", 0)
        self.retry = {}

    def step(self):
        now = time.time()
        today = int(now // 86400) * 86400
        if today != self.lv_day or not self.lv:
            new = {}
            for c in COINS:
                try:
                    x = levels_for(c)
                    if x: new[c] = x
                except Exception as e:  # noqa: BLE001
                    log.warning("turtle niveles %s: %s", c, e)
            if len(new) == len(COINS):
                self.lv, self.lv_day = new, today
        try:
            mids = requests.post(HL, json={"type": "allMids"}, timeout=15).json()
            px = {c: float(mids[c]) for c in COINS if c in mids}
        except Exception as e:  # noqa: BLE001
            log.warning("turtle precios: %s", e); return
        eq = self.radar.plan_equity("lloyd")
        for c in COINS:
            L = self.lv.get(c); p = px.get(c)
            if not L or not p:
                continue
            if c in self.pos:
                self.manage(c, p, L, now)
            elif self.mode != "off" and now >= self.retry.get(c, 0):
                if p >= L["buy_above"]:
                    self.try_open(c, "long", p, L["buy_above"], L["long_exit_below"], eq, now)
                elif p <= L["short_below"]:
                    if c == "SOL" and (self.leg.get("pos") or {}).get("side") == "short":
                        continue
                    self.try_open(c, "short", p, L["short_below"], L["short_exit_above"], eq, now)
        out = {}
        for c in COINS:
            L = self.lv.get(c); p = px.get(c)
            if not L or not p:
                continue
            out[c] = {**L, "px": p, "to_buy": round(L["buy_above"] / p - 1, 4), "to_short": round(L["short_below"] / p - 1, 4), "position": self.pos.get(c)}
        jsave(LEVELS, {"ts": now, "day": self.lv_day, "mode": self.mode, "rules": R, "levels": self.lv, "view": out})

    def try_open(self, coin, side, price, level, exit_lv, eq, now):
        if abs(price / level - 1) > R["chase"]:
            return   # el precio ya pasó el nivel por más de 1%: hueco, no se persigue (espera el próximo toque)
        dist = abs(exit_lv / price - 1)
        if dist <= 0.005 or eq <= 0:
            return
        notional = R["risk"] * eq / dist
        coll = min(notional / R["lev"], R["coll_max_frac"] * eq)
        if coll < R["coll_min"]:
            if R["coll_min"] * R["lev"] * dist > R["risk_max"] * eq:
                return
            coll = R["coll_min"]
        coll = round(coll, 2)
        rec = {"ts": now, "leg": "book", "plan": "lloyd", "symbol": coin, "side": side, "entry": price, "level": level, "exit_level": exit_lv,
               "collateral_usd": coll, "lev": R["lev"], "size_usd": round(coll * R["lev"], 2), "risk_usd": round(coll * R["lev"] * dist, 2), "mode": self.mode,
               "pubkey": None, "reason": "majors_trend", "system": "turtle55"}
        if self.mode == "live":
            try:
                r = self.radar.perps(self.leg).open(coin, side, coll, R["lev"], dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                self.retry[coin] = now + 300
                self.rlog("turtle_open_failed", coin=coin, side=side, error=str(r.get("error"))[:300]); log.error("turtle: no abrió %s %s: %s", side, coin, r.get("error"))
                return
            rec.update({"pubkey": r.get("position_pubkey"), "sig": r.get("sig")})
            try:
                live = [q for q in self.radar.perps(self.leg).positions() if q.get("pubkey") == rec["pubkey"]]
                if live and live[0].get("entry"): rec["entry"] = float(live[0]["entry"])
            except Exception:  # noqa: BLE001
                pass
        self.pos[coin] = rec; jsave(POS, self.pos); self.rlog("turtle_open", **rec)
        what = "55-day high" if side == "long" else "55-day low"
        self.note(f"Breakout: {side} {coin}",
                  f"{coin} touched its {what} (${level:,.2f}), a level Lloyd had on file. Turtle rule (55/20): open a {side} on Jupiter Perps at 2x, "
                  f"${coll:.0f} collateral (${coll * R['lev']:.0f} exposure), entry ${rec['entry']:,.2f}. The exit is pre-set at the 20-day "
                  f"{'low' if side == 'long' else 'high'} (${exit_lv:,.2f}); if it is hit, the loss is about ${rec['risk_usd']:.1f} (1% of the book). "
                  f"Why: in 2024–26 this rule made +7% per trade on average across 8 crypto markets (t 2.0, beats random entries). "
                  f"Against: most breakouts fail (55–65% of trades lose); the system lives on the few big moves.")

    def manage(self, coin, price, L, now):
        p = self.pos[coin]; d = 1 if p["side"] == "long" else -1
        # la salida se mueve con cada cierre diario, solo a favor (como un trailing)
        ex = L["long_exit_below"] if d > 0 else L["short_exit_above"]
        p["exit_level"] = max(p["exit_level"], ex) if d > 0 else min(p["exit_level"], ex)
        ret = d * (price / p["entry"] - 1)
        p.update({"mark": price, "ret_px": round(ret, 4), "pnl_usd_est": round(ret * p["size_usd"], 2), "age_d": round((now - p["ts"]) / 86400, 2)})
        hit = price <= p["exit_level"] if d > 0 else price >= p["exit_level"]
        if hit:
            self.close(coin, f"touched the exit level ${p['exit_level']:,.2f}", price, now)
        else:
            jsave(POS, self.pos)

    def close(self, coin, why, price, now):
        p = self.pos[coin]
        if p.get("mode") == "live" and p.get("pubkey"):
            try:
                r = self.radar.perps(self.leg).close(p["pubkey"], dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                p["close_attempts"] = p.get("close_attempts", 0) + 1; jsave(POS, self.pos)
                self.rlog("turtle_close_failed", coin=coin, error=str(r.get("error"))[:300])
                if p["close_attempts"] < 5:
                    return
        d = 1 if p["side"] == "long" else -1
        ret = d * (price / p["entry"] - 1); pnl = ret * p["size_usd"] - p["size_usd"] * 0.0012 * 2
        row = {"ts": now, "ts_open": p["ts"], "leg": "book", "symbol": coin, "side": p["side"], "entry": p["entry"], "exit": price,
               "collateral_usd": p["collateral_usd"], "size_usd": p["size_usd"], "ret_px": round(ret, 4), "pnl_usd": round(pnl, 2),
               "hold_h": round((now - p["ts"]) / 3600, 2), "why": why, "mode": p.get("mode"), "reason": "majors_trend", "system": "turtle55"}
        with open(CLOSED, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.rlog("turtle_close", **row)
        self.note(f"Breakout trade closed: {p['side']} {coin}",
                  f"Closed: {why}. Entry ${p['entry']:,.2f}, exit ${price:,.2f}, result about ${pnl:+.2f} on ${p['collateral_usd']:.0f} collateral.")
        del self.pos[coin]; jsave(POS, self.pos)

    @staticmethod
    def rlog(kind, **kw):
        with open(ST / "radar_log.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, **kw}, ensure_ascii=False) + "\n")

    @staticmethod
    def note(title, text):
        d = Path("state/plan_lloyd/auto")
        did = f"auto-lloyd-turtle-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
        jsave(d / f"{did}.json", {"id": did, "title": title, "journal": text, "orders": [], "auto": True})
