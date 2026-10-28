"""Cerebro continuo de las mesas (28/10/2026). Corre cada 10 minutos, 24/7, y decide con reglas fijas entre las sesiones de Claude.

No ejecuta nada por su cuenta: escribe decisiones (mismo formato que las de Claude) en state/<mesa>/auto/*.json y el motor
(`engine.py`) las ejecuta con todos sus frenos. Así hay un solo lugar que firma transacciones.

Qué hace, por perfil de mesa:
- Agresivo (mesa principal y plan agresivo):
  1. Stops que suben solos según el pico: a 1,3x asegura entrada (+2%), desde 1,6x asegura 75% del pico, desde 3x el 70%.
     Solo ajusta hacia arriba; nunca afloja un stop puesto a mano.
  2. Efectivo ocioso > 15% del patrimonio → compra el mejor candidato del escaneo que pase el anti-rug (LIMPIO).
  3. Rotación: posición con más de 36 h, sin haber pasado 1,25x y entre 0,85x y 1,12x = plata dormida; si hay un candidato
     verificado, la vende y mueve el capital.
  4. Régimen de mercado: si SOL cae fuerte (≤ −6% en 24 h o ≤ −4% en 4 h) no abre memecoins por 6 h y asegura entrada en
     todo lo que ya ganó 15%.
  Límites: máx 3 posiciones, máx 35% del patrimonio por compra, máx 2 compras automáticas por día, nada recomprado dentro de
  48 h de su cierre, nada con suba > 60% en 24 h o > 30% en 6 h, ni fuera de un retroceso sano
  (55–90% del máximo de 3 días, 24 h entre −40% y +60%), ni con volumen < 30% de la mcap, < 1.000 holders o en la lista de
  volumen fabricado (DOAS, JEANPHIL, USDF, USOE, Verse + state/desk/blacklist.json). Escaneo de menos de 2,5 h.
- Equilibrado: solo stops que suben solos (más cortos).
- Tradicional: la regla del plan (SOL, BTC, ETH, JUP por encima del promedio de 20 días, un cuarto del plan cada uno; el resto
  en USDC), revisada cada hora en vez de dos veces por día, con banda de 1% para no entrar y salir por ruido.

Modo por mesa en state/brain_config.json: {"modes": {"mesa": "live", "agresivo": "live", ...}}; "shadow" = solo registra lo
que haría (state/<mesa>/brain_shadow.jsonl). Estado visible en state/<mesa>/brain.json (lo publica el motor).
Uso: python -m fomo_intel.desk.brain [--once] [--shadow]
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

log = logging.getLogger("brain")
HL = "https://api.hyperliquid.xyz/info"
JUP_PRICE = "https://api.jup.ag/price/v3"
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
STABLES = {USDC, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
# activos del plan tradicional: símbolo en Hyperliquid (para la tendencia) → mint en Solana (para operar)
TRAD = {"SOL": SOL_MINT, "BTC": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij", "ETH": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
        "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"}

DESKS = {
    "mesa": {"name": "", "profile": "aggressive", "lang": "es"},
    "agresivo": {"name": "agresivo", "profile": "fast", "lang": "en"},
    "equilibrado": {"name": "equilibrado", "profile": "balanced", "lang": "en"},
    "tradicional": {"name": "tradicional", "profile": "traditional", "lang": "en"},
}
DEFAULT_MODES = {"mesa": "shadow", "agresivo": "shadow", "equilibrado": "shadow", "tradicional": "shadow"}
CFG = Path("state/brain_config.json")
SCAN_JSON = Path("state/desk/scan4.json")
SCAN_FAST = Path("state/desk/scan_fast.json")
# Perfil "rápido" (plan agresivo, desde 28/10 21:00 ART, pedido de Gastón: "todo demasiado estático"). El plan se vende como
# memecoins de US$300K–3M: hasta ahora tenía tokens de US$3–15M (los mismos que la mesa) y el escaneo, con liquidez mínima de
# US$150K, casi no veía esa franja. Ahora: su propia franja, 2 posiciones concentradas, salidas más cortas, rotación a las 12 h.
# No hay backtest que pruebe que esto rinde más: compra más movimiento (varianza), con freno diario.
FAST = {"since": 1793229600, "max_pos": 2, "max_frac": 0.48, "min_buy_sol": 0.15, "max_auto_buys_day": 4, "scan_every_h": 1,
        "stale_h": 12, "stale_peak": 1.15, "day_brake": 0.12, "mcap_lo": 3e5, "mcap_hi": 3e6, "min_vol_mcap": 0.5, "min_holders": 500,
        "max_top10": 35, "min_ch24h": -0.3, "max_ch24h": 1.0, "min_ch6h": -0.05, "max_ch6h": 0.4, "min_from_hi": 0.6, "max_from_hi": 0.92,
        "min_ch1h": -0.10, "stop": 0.25, "trail": 0.25, "trail_after": 1.3, "tp": [[1.5, 0.4], [2.5, 0.3]]}
SCAN_FAST_ENV = {"SCAN_LO": "300000", "SCAN_HI": "3000000", "SCAN_LIQ": "60000", "SCAN_AGE_H": "6", "SCAN_VOLMCAP": "0.5",
                 "SCAN_TOP10": "35", "SCAN_MIN_CANDLES": "8", "SCAN_OUT": str(SCAN_FAST)}
DD_DIR = Path("state/desk/dd")

LIM = {"max_pos": 3, "max_frac": 0.35, "min_buy_sol": 0.08, "idle_frac": 0.15, "max_auto_buys_day": 2, "cooldown_h": 48,
       "stale_h": 36, "scan_every_h": 2, "dd_max_age_h": 6, "mcap_lo": 3e5, "mcap_hi": 3e7, "max_ch24h": 0.6, "min_ch24h": -0.4, "max_ch6h": 0.3,
       "max_from_hi": 0.9, "min_from_hi": 0.55, "min_vol_mcap": 0.3, "min_holders": 1000, "max_scan_age_h": 2.5, "max_bundlers": 15.0}
# volumen fabricado por bots (regla 3 de la mesa); se suma state/desk/blacklist.json ({"mints": [...], "symbols": [...]})
BLACK_SYMS = {"JEANPHIL", "DOAS", "USDF", "USOE", "VERSE"}
BLACK_MINTS = {"27Fe2sET619et2hXBBJXdabBK7ScD5UNym64u6Dqpump"}


def jload(p, d):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def jsave(p, o):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp"); json.dump(o, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def paths(d):
    n = d["name"]
    if n:
        return Path(f"state/plan_{n}"), Path(f"state/plan_{n}_summary.json")
    return Path("state/desk"), Path("state/desk_summary.json")


def L(d, es, en):
    return es if d["lang"] == "es" else en


# ------------------------------------------------------------ datos de mercado
def hl_daily(coin, days=40):
    end = int(time.time() * 1000)
    try:
        r = requests.post(HL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": end - days * 86400000, "endTime": end}}, timeout=20)
        cs = r.json() if r.ok else []
        return [(int(c["t"]) // 1000, float(c["c"])) for c in cs]
    except Exception as e:  # noqa: BLE001
        log.warning("hyperliquid %s: %s", coin, e); return []


def trend(coin):
    """Precio, promedio de 20 días (con cierres diarios) y cambios de 4 h y 24 h."""
    h = hl_daily(coin)
    if len(h) < 24 * 21:
        return None
    closes_d = [c for t, c in h if (t // 3600) % 24 == 23][-20:]
    if len(closes_d) < 15:
        return None
    px = h[-1][1]
    return {"px": px, "ma20": sum(closes_d) / len(closes_d), "ch4h": px / h[-5][1] - 1, "ch24h": px / h[-25][1] - 1}


def jup_prices(mints):
    key = os.getenv("JUPITER_API_KEY", "")
    if not key or not mints:
        return {}
    try:
        r = requests.get(JUP_PRICE, params={"ids": ",".join(mints)}, headers={"x-api-key": key}, timeout=10)
        return {m: float((v or {}).get("usdPrice") or 0) for m, v in r.json().items()}
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------ cerebro
class Brain:
    def __init__(self, force_shadow=False):
        self.force_shadow = force_shadow
        self.regime = {"state": "neutral", "ts": 0}
        self.trend_cache: dict = {}
        self.last_scan = jload(Path("state/desk/brain_scan.json"), {}).get("ts", 0)
        self.last_scan_fast = jload(Path("state/desk/brain_scan.json"), {}).get("fast_ts", 0)

    def modes(self):
        m = {**DEFAULT_MODES, **jload(CFG, {}).get("modes", {})}
        return {k: ("shadow" if self.force_shadow else v) for k, v in m.items()}

    # ---------- régimen ----------
    def update_regime(self):
        if time.time() - self.regime["ts"] < 600:
            return
        t = trend("SOL")
        if not t:
            return
        prev = self.regime
        state = "neutral"
        if t["ch24h"] <= -0.06 or t["ch4h"] <= -0.04:
            state = "risk_off"
        elif prev.get("state") == "risk_off" and time.time() - prev.get("since", 0) < 6 * 3600:
            state = "risk_off"                                     # se queda 6 h en defensa
        elif t["px"] > t["ma20"] and t["ch24h"] > 0:
            state = "risk_on"
        since = prev.get("since", time.time()) if state == prev.get("state") else time.time()
        self.regime = {"state": state, "ts": time.time(), "since": since, "sol": round(t["px"], 2), "sol_ma20": round(t["ma20"], 2),
                       "sol_ch4h": round(t["ch4h"] * 100, 1), "sol_ch24h": round(t["ch24h"] * 100, 1)}
        jsave(Path("state/desk/regime.json"), self.regime)

    # ---------- candidatos (escaneo + anti-rug) ----------
    def refresh_candidates(self, need):
        """Corre el escaneo amplio cada 2 h (solo si alguna mesa necesita candidatos) y el anti-rug de los 5 mejores."""
        if not need or time.time() - self.last_scan < LIM["scan_every_h"] * 3600:
            return
        self.last_scan = time.time(); jsave(Path("state/desk/brain_scan.json"), {"ts": self.last_scan, "fast_ts": self.last_scan_fast})
        log.info("escaneo scan4…")
        try:
            subprocess.run([sys.executable, "-m", "fomo_intel.desk.scan4"], timeout=1200, capture_output=True)
        except Exception as e:  # noqa: BLE001
            log.warning("scan4 falló: %s", e); return
        top = [v["mint"] for v in jload(SCAN_JSON, {}).get("ok", [])[:6]]
        stale = [m for m in top if time.time() - jload(DD_DIR / f"{m}.json", {}).get("ts", 0) > LIM["dd_max_age_h"] * 3600]
        if stale:
            try:
                subprocess.run([sys.executable, "-m", "fomo_intel.desk.dd", *stale], timeout=1500, capture_output=True)
            except Exception as e:  # noqa: BLE001
                log.warning("dd falló: %s", e)

    def refresh_fast(self, need):
        """Escaneo de la franja chica (US$300K–3M, liquidez ≥ US$60K, edad ≥ 6 h) cada hora + anti-rug de los 4 mejores."""
        if not need or time.time() - self.last_scan_fast < FAST["scan_every_h"] * 3600:
            return
        self.last_scan_fast = time.time(); jsave(Path("state/desk/brain_scan.json"), {"ts": self.last_scan, "fast_ts": self.last_scan_fast})
        log.info("escaneo rápido (franja chica)…")
        try:
            subprocess.run([sys.executable, "-m", "fomo_intel.desk.scan4"], timeout=1200, capture_output=True, env={**os.environ, **SCAN_FAST_ENV})
        except Exception as e:  # noqa: BLE001
            log.warning("escaneo rápido falló: %s", e); return
        top = [v["mint"] for v in self.fast_candidates(set(), set(), need_dd=False)[:4]]
        stale = [m for m in top if time.time() - jload(DD_DIR / f"{m}.json", {}).get("ts", 0) > LIM["dd_max_age_h"] * 3600]
        if stale:
            try:
                subprocess.run([sys.executable, "-m", "fomo_intel.desk.dd", *stale], timeout=1200, capture_output=True)
            except Exception as e:  # noqa: BLE001
                log.warning("dd falló: %s", e)

    def fast_candidates(self, held, cooled, need_dd=True):
        sc = jload(SCAN_FAST, {})
        if time.time() - sc.get("ts", 0) > 2 * 3600:
            return []
        bl = jload(Path("state/desk/blacklist.json"), {})
        bmints = BLACK_MINTS | set(bl.get("mints", [])); bsyms = BLACK_SYMS | {x.upper() for x in bl.get("symbols", [])}
        out = []
        for v in sc.get("ok", [])[:15]:
            m = v["mint"]; F = FAST
            if m in held or m in cooled or m in bmints or (v.get("sym") or "").upper() in bsyms:
                continue
            if not (F["mcap_lo"] <= (v.get("mcap") or 0) <= F["mcap_hi"]) or (v.get("vol_mcap") or 0) < F["min_vol_mcap"] \
                    or (v.get("holders") or 0) < F["min_holders"] or (v.get("top10") or 100) >= F["max_top10"]:
                continue
            # se está moviendo (6 h no negativas) pero entramos en un retroceso, no en el pico
            if not (F["min_ch24h"] <= (v.get("ch24h") or 0) <= F["max_ch24h"]) or not (F["min_ch6h"] <= (v.get("ch6h") or 0) <= F["max_ch6h"]) \
                    or not (F["min_from_hi"] <= (v.get("from_hi") or 1) <= F["max_from_hi"]) or (v.get("ch1h") or 0) < F["min_ch1h"]:
                continue
            if not need_dd:
                out.append(v); continue
            dd = jload(DD_DIR / f"{m}.json", {})
            if dd.get("verdict") != "LIMPIO" or time.time() - dd.get("ts", 0) > LIM["dd_max_age_h"] * 3600 * 2:
                continue
            if ((dd.get("risk") or {}).get("bundlers%") or 0) > LIM["max_bundlers"]:
                continue
            out.append({**v, "dd": dd, "factory": ((dd.get("deployer") or {}).get("lanzamientos") or 0) > 200})
        return out

    def candidates(self, held, cooled):
        sc = jload(SCAN_JSON, {})
        if time.time() - sc.get("ts", 0) > LIM["max_scan_age_h"] * 3600:
            return []
        bl = jload(Path("state/desk/blacklist.json"), {})
        bmints = BLACK_MINTS | set(bl.get("mints", [])); bsyms = BLACK_SYMS | {x.upper() for x in bl.get("symbols", [])}
        out = []
        for v in sc.get("ok", [])[:8]:
            m = v["mint"]
            if m in held or m in cooled or m in bmints or (v.get("sym") or "").upper() in bsyms:
                continue
            if (v.get("vol_mcap") or 0) < LIM["min_vol_mcap"] or (v.get("holders") or 0) < LIM["min_holders"]:
                continue
            if not (LIM["mcap_lo"] <= (v.get("mcap") or 0) <= LIM["mcap_hi"]):
                continue
            # comprar en retroceso, no en la vela de euforia (regla 4 de la mesa): al menos 10% bajo el máximo de 3 días
            # y tampoco un derrumbe (−98% en 24 h = dato roto o token muerto): retroceso sano = 55–90% del máximo de 3 días
            ch24, fh = v.get("ch24h") or 0, v.get("from_hi") or 1
            if not (LIM["min_ch24h"] <= ch24 <= LIM["max_ch24h"]) or (v.get("ch6h") or 0) > LIM["max_ch6h"] \
                    or not (LIM["min_from_hi"] <= fh <= LIM["max_from_hi"]) or (v.get("ch1h") or 0) < -0.15:
                continue
            dd = jload(DD_DIR / f"{m}.json", {})
            if dd.get("verdict") != "LIMPIO" or time.time() - dd.get("ts", 0) > LIM["dd_max_age_h"] * 3600 * 2:
                continue
            bund = (dd.get("risk") or {}).get("bundlers%") or 0
            if bund and bund > LIM["max_bundlers"]:
                continue
            factory = ((dd.get("deployer") or {}).get("lanzamientos") or 0) > 200
            out.append({**v, "dd": dd, "factory": factory})
        return out

    # ---------- reglas ----------
    @staticmethod
    def lock_for(profile, peak, regime):
        """Múltiplo que se asegura dado el pico. None = no ajustar."""
        lock = None
        if profile == "aggressive":
            if peak >= 3: lock = peak * 0.70
            elif peak >= 1.6: lock = peak * 0.75
            elif peak >= 1.3: lock = 1.02
        elif profile == "fast":
            if peak >= 1.6: lock = peak * 0.80
            elif peak >= 1.3: lock = 1.05
        elif profile == "balanced":
            if peak >= 1.4: lock = peak * 0.85
            elif peak >= 1.2: lock = 1.01
        if regime == "risk_off" and peak >= 1.15:
            lock = max(lock or 0, 1.01)
        return lock

    def ratchet(self, d, s, regime):
        orders, notes = [], []
        for p in s.get("positions", []):
            if p["mint"] in STABLES or p.get("brain") is False or d["profile"] == "traditional":
                continue
            peak = p["peak_usd"] / p["entry_usd"]
            lock = self.lock_for(d["profile"], peak, regime)
            if not lock:
                continue
            new_stop = round(1 - lock, 3)
            if new_stop < float(p["stop"]) - 0.01 and (p.get("mult") or 0) > lock * 1.01:
                orders.append({"action": "set", "mint": p["mint"], "stop": new_stop})
                notes.append(L(d, f"{p['symbol']}: llegó a {peak:.2f}x de pico; subo el stop a {lock:.2f}x (antes {1 - float(p['stop']):.2f}x).",
                               f"{p['symbol']}: peaked at {peak:.2f}x; stop raised to {lock:.2f}x (was {1 - float(p['stop']):.2f}x)."))
        return orders, notes

    def aggressive(self, d, s, st_dir, regime, bstate):
        orders, notes = [], []
        sol_usd = s.get("sol_usd") or 100
        eq_sol = s["equity_usd"] / sol_usd
        held = {p["mint"] for p in s.get("positions", [])}
        now = time.time()
        cooled = {c["mint"] for c in s.get("closed", []) if now - c.get("ts", 0) < LIM["cooldown_h"] * 3600}
        today = time.strftime("%Y-%m-%d", time.localtime(now - 3 * 3600))
        buys_today = [b for b in bstate.get("auto_buys", []) if b.get("day") == today]
        cands = self.candidates(held, cooled)
        free = s.get("cash_sol", 0) - 0.03 - 0.02
        npos = len([p for p in s.get("positions", []) if p["mint"] not in STABLES])
        # rotación: plata dormida
        stale = []
        for p in s.get("positions", []):
            age_h = (now - p.get("opened_ts", now)) / 3600
            peak = p["peak_usd"] / p["entry_usd"]
            if p["mint"] not in STABLES and age_h >= LIM["stale_h"] and peak < 1.25 and 0.85 <= (p.get("mult") or 1) <= 1.12 and p.get("brain") is not False:
                stale.append(p)
        if regime == "risk_off":
            if free > eq_sol * LIM["idle_frac"]:
                notes.append(L(d, f"Efectivo ocioso ({free / eq_sol:.0%}), pero SOL cae fuerte ({self.regime.get('sol_ch24h')}% en 24 h): no abro memecoins hasta que se calme.",
                               f"Idle cash ({free / eq_sol:.0%}), but SOL is falling hard ({self.regime.get('sol_ch24h')}% in 24h): no new memecoins until it calms down."))
            return orders, notes, []
        if len(buys_today) >= LIM["max_auto_buys_day"]:
            return orders, notes, []
        new_buys = []
        if stale and cands:
            p = min(stale, key=lambda x: x.get("mult") or 1)
            c = cands.pop(0)
            sol = min(p["value_usd"] / sol_usd * 0.97, eq_sol * LIM["max_frac"])
            orders.append({"action": "sell", "mint": p["mint"], "frac": 1.0, "why": L(d, "rotación: plata dormida", "rotation: dead money")})
            orders.append(self.buy_order(d, c, sol))
            notes.append(L(d, f"Roto {p['symbol']}: {(now - p['opened_ts']) / 3600:.0f} h quieto en {p.get('mult', 1):.2f}x (nunca pasó {p['peak_usd'] / p['entry_usd']:.2f}x). "
                              f"El capital va a {c['sym']}.", f"Rotating out of {p['symbol']}: flat at {p.get('mult', 1):.2f}x for {(now - p['opened_ts']) / 3600:.0f}h "
                              f"(never above {p['peak_usd'] / p['entry_usd']:.2f}x). Capital moves to {c['sym']}."))
            notes.append(self.thesis_note(d, c)); new_buys.append(c["sym"])
        elif free > eq_sol * LIM["idle_frac"] and npos < LIM["max_pos"] and cands:
            c = cands.pop(0)
            sol = min(free, eq_sol * LIM["max_frac"]) * (0.5 if c["factory"] else 1.0)
            if sol >= LIM["min_buy_sol"]:
                orders.append(self.buy_order(d, c, sol))
                notes.append(L(d, f"Efectivo ocioso: {free:.3f} SOL ({free / eq_sol:.0%} del patrimonio). Lo pongo a trabajar en {c['sym']}.",
                               f"Idle cash: {free:.3f} SOL ({free / eq_sol:.0%} of the plan). Putting it to work in {c['sym']}."))
                notes.append(self.thesis_note(d, c)); new_buys.append(c["sym"])
        elif free > eq_sol * LIM["idle_frac"] and npos < LIM["max_pos"] and now - bstate.get("_noted_no_cands", 0) > 12 * 3600:
            notes.append(L(d, f"Efectivo ocioso ({free / eq_sol:.0%}) sin candidato que pase el escaneo y el anti-rug. Prefiero esperar a comprar algo peor.",
                           f"Idle cash ({free / eq_sol:.0%}) but no candidate passes the scan and the anti-rug check. Waiting beats buying something worse."))
            bstate["_noted_no_cands"] = now
        return orders, notes, new_buys

    def fast(self, d, s, regime, bstate):
        """Plan agresivo: franja chica, 2 posiciones concentradas, rotación a las 12 h, freno diario de −12%."""
        F = FAST; orders, notes, new_buys = [], [], []
        now = time.time(); sol_usd = s.get("sol_usd") or 100; eq_sol = s["equity_usd"] / sol_usd
        today = time.strftime("%Y-%m-%d", time.localtime(now - 3 * 3600))
        if bstate.get("day") != today:
            bstate["day"] = today; bstate["day_start_usd"] = s["equity_usd"]
        pos = [p for p in s.get("positions", []) if p["mint"] not in STABLES and p.get("brain") is not False]
        held = {p["mint"] for p in s.get("positions", [])}
        cooled = {c["mint"] for c in s.get("closed", []) if now - c.get("ts", 0) < LIM["cooldown_h"] * 3600}
        legacy = [p for p in pos if p.get("opened_ts", 0) < F["since"]]          # de antes del cambio: fuera de la franja del plan
        dead = [p for p in pos if p not in legacy and (now - p.get("opened_ts", now)) / 3600 >= F["stale_h"]
                and p["peak_usd"] / p["entry_usd"] < F["stale_peak"]]
        # 1) plata dormida: a las 12 h sin haber pasado 1,15x, afuera (aunque no haya candidato: el efectivo se recoloca en la hora)
        for p in dead:
            orders.append({"action": "sell", "mint": p["mint"], "frac": 1.0, "why": "time stop: no move in 12h"})
            notes.append(f"{p['symbol']}: {(now - p['opened_ts']) / 3600:.0f}h in, never above {p['peak_usd'] / p['entry_usd']:.2f}x, now {p.get('mult', 1):.2f}x. "
                         f"This plan pays for movement; a flat token is dead money. Sold.")
        brake = s["equity_usd"] < bstate.get("day_start_usd", s["equity_usd"]) * (1 - F["day_brake"])
        buys_today = [b for b in bstate.get("auto_buys", []) if b.get("day") == today]
        if regime == "risk_off" or brake or len(buys_today) >= F["max_auto_buys_day"]:
            if brake and not bstate.get("_brake_noted") == today:
                notes.append(f"Daily brake: the plan is down more than {F['day_brake']:.0%} today (from ${bstate['day_start_usd']:.0f} to ${s['equity_usd']:.0f}). "
                             "No new positions until tomorrow; open ones keep their stops.")
                bstate["_brake_noted"] = today
            return orders, notes, new_buys
        cands = self.fast_candidates(held, cooled)
        free = s.get("cash_sol", 0) - 0.05 + sum(p["value_usd"] / sol_usd * 0.97 for p in dead)
        slots = F["max_pos"] - (len(pos) - len(dead) - len(legacy))
        # 2) efectivo (o lo que liberó el time stop) → mejor candidato de la franja
        while cands and slots > 0 and free >= F["min_buy_sol"] and len(new_buys) + len(buys_today) < F["max_auto_buys_day"]:
            c = cands.pop(0)
            sol = min(free, eq_sol * F["max_frac"]) * (0.5 if c["factory"] else 1.0)
            if sol < F["min_buy_sol"]:
                break
            orders.append(self.fast_buy(c, sol)); notes.append(self.thesis_note(d, c)); new_buys.append(c["sym"])
            free -= sol; slots -= 1
        # 3) posiciones viejas (fuera de la franja): se rotan a medida que aparecen candidatos, la más débil primero
        legacy.sort(key=lambda p: p.get("mult") or 1)
        n_fast = len(pos) - len(dead) - len(legacy) + len(new_buys)
        while legacy and cands and len(new_buys) + len(buys_today) < F["max_auto_buys_day"] and n_fast < F["max_pos"]:
            p = legacy.pop(0); c = cands.pop(0)
            sol = min(p["value_usd"] / sol_usd * 0.97 + max(free, 0), eq_sol * F["max_frac"])
            orders.append({"action": "sell", "mint": p["mint"], "frac": 1.0, "why": "rotation into the plan's own range"})
            orders.append(self.fast_buy(c, sol)); new_buys.append(c["sym"]); free = 0; n_fast += 1
            notes.append(f"Rotating {p['symbol']} ({p.get('mult', 1):.2f}x) out: it is a larger, slower token than this plan is meant to hold. Capital moves to {c['sym']}.")
            notes.append(self.thesis_note(d, c))
        if not orders and s.get("cash_sol", 0) - 0.05 > eq_sol * LIM["idle_frac"] and now - bstate.get("_noted_no_cands", 0) > 6 * 3600:
            notes.append("Idle cash, but nothing in the $300K–3M range passes the filters and the anti-rug check this hour. The range is rescanned every hour.")
            bstate["_noted_no_cands"] = now
        return orders, notes, new_buys

    def fast_buy(self, c, sol):
        F = FAST
        return {"action": "buy", "mint": c["mint"], "symbol": c["sym"], "sol": round(sol, 4), "stop": F["stop"], "trail": F["trail"], "trail_after": F["trail_after"],
                "tp": F["tp"], "thesis": f"Fast plan: ${c['mcap'] / 1e6:.1f}M token moving ({c['ch24h']:+.0%} 24h) bought on a pullback ({c['from_hi']:.0%} of its 3-day high); clean anti-rug check. "
                                         "Exit plan: sell 40% at 1.5x, 30% at 2.5x, trail 25% after 1.3x, stop −25%, out at 12h if it never passes 1.15x."}

    def buy_order(self, d, c, sol):
        stop = 0.30 if (c.get("mcap") or 0) >= 2e6 else 0.35
        return {"action": "buy", "mint": c["mint"], "symbol": c["sym"], "sol": round(sol, 4), "stop": stop, "trail": 0.35, "trail_after": 1.6,
                "tp": [[3, 0.25], [6, 0.25]], "thesis": L(d, "Compra automática del cerebro: escaneo + anti-rug LIMPIO.", "Automatic buy: passed the scan and a clean anti-rug check.")}

    def thesis_note(self, d, c):
        dd = c["dd"]; r = dd.get("risk") or {}
        return L(d,
                 f"{c['sym']}: US${c['mcap'] / 1e6:.1f}M, liquidez US${c['liq'] / 1e3:.0f}K, volumen 24 h {c['vol_mcap']:.1f}x su valor, {c.get('holders')} holders, top 10 {c.get('top10', 0):.0f}%; "
                 f"24 h {c['ch24h']:+.0%}, {c['from_hi']:.0%} del máximo de 3 días. Anti-rug LIMPIO (grupos con fondeador común {dd.get('clusters_sospechosos_pct')}%). "
                 f"En contra: bundlers {r.get('bundlers%') or 0:.0f}%" + (", creador con muchos lanzamientos (tamaño a la mitad)" if c["factory"] else "") + "; un stop de 30–35% puede ejecutarse más abajo en una caída rápida.",
                 f"{c['sym']}: ${c['mcap'] / 1e6:.1f}M market cap, ${c['liq'] / 1e3:.0f}K liquidity, 24h volume {c['vol_mcap']:.1f}x its value, {c.get('holders')} holders, top 10 hold {c.get('top10', 0):.0f}%; "
                 f"24h {c['ch24h']:+.0%}, at {c['from_hi']:.0%} of its 3-day high. Anti-rug: clean (common-funder groups {dd.get('clusters_sospechosos_pct')}%). "
                 f"Against: bundlers {r.get('bundlers%') or 0:.0f}%" + (", creator launched many tokens (half size)" if c["factory"] else "") + ("; a 25% stop can fill lower in a fast drop; small tokens can halve in an hour." if d["profile"] == "fast" else "; a 30–35% stop can fill lower in a fast drop."))

    def traditional(self, d, s, bstate):
        """Regla del plan: cada activo arriba de su promedio de 20 días (+1%) ocupa un cuarto del plan; abajo (−1%) vuelve a USDC."""
        if time.time() - bstate.get("trad_ts", 0) < 3600:
            return [], []
        bstate["trad_ts"] = time.time()
        sol_usd = s.get("sol_usd") or 100
        eq = s["equity_usd"]; slot = eq / 4
        pos = {p["mint"]: p for p in s.get("positions", [])}
        usdc = pos.get(USDC)
        usdc_val = (usdc or {}).get("value_usd", 0)
        cash_free = max(0.0, s.get("cash_sol", 0) - 0.03 - 0.02)
        sells, buys, notes, status = [], [], [], []
        for coin, mint in TRAD.items():
            t = trend(coin)
            if not t:
                continue
            gap = t["px"] / t["ma20"] - 1
            status.append(f"{coin} {gap:+.1%}")
            if coin == "SOL":
                held = cash_free * sol_usd >= slot * 0.5
            else:
                held = mint in pos
            if gap > 0.01 and not held:
                if coin != "SOL":
                    buys.append({"action": "buy", "mint": mint, "symbol": coin, "sol": round(slot / sol_usd * 0.98, 4), "stop": 0.5, "trail": 0.5, "trail_after": 50, "tp": [],
                                 "thesis": f"{coin} is {gap:+.1%} above its 20-day average.", "_need_usd": slot})
                else:
                    buys.append({"_sol_slot": True, "_need_usd": slot})
                notes.append(f"{coin} closed above its 20-day average ({gap:+.1%}): it takes a quarter of the plan.")
            elif gap < -0.01 and held:
                if coin != "SOL":
                    sells.append({"action": "sell", "mint": mint, "frac": 1.0, "why": "below 20-day average"})
                    sells.append({"action": "buy", "mint": USDC, "symbol": "USDC", "sol": round(pos[mint]["value_usd"] / sol_usd * 0.97, 4), "stop": 0.05, "trail": 0.5,
                                  "trail_after": 10, "tp": [], "thesis": "Cash parked in USDC."})
                else:
                    sells.append({"action": "buy", "mint": USDC, "symbol": "USDC", "sol": round(min(cash_free, slot / sol_usd), 4), "stop": 0.05, "trail": 0.5,
                                  "trail_after": 10, "tp": [], "thesis": "Cash parked in USDC."})
                notes.append(f"{coin} fell below its 20-day average ({gap:+.1%}): back to USDC.")
        bstate["trad_status"] = ", ".join(status)
        orders = list(sells)
        need = sum(b["_need_usd"] for b in buys)
        if buys and usdc and usdc_val > 5:
            frac = min(1.0, need / usdc_val) * usdc["tokens"] / (usdc.get("tokens_initial") or usdc["tokens"])   # el motor mide frac sobre las fichas iniciales
            orders.append({"action": "sell", "mint": USDC, "frac": round(frac, 4) if frac < 0.999 else 1.0, "why": "fund trend position"})
        for b in buys:
            if b.get("_sol_slot"):
                continue
            orders.append({k: v for k, v in b.items() if not k.startswith("_")})
        return orders, notes

    # ---------- ciclo ----------
    def run_desk(self, key, d, mode):
        st_dir, summ = paths(d)
        st_dir.mkdir(parents=True, exist_ok=True)
        s = jload(summ, {})
        bstate = jload(st_dir / "brain.json", {})
        bstate.update({"mode": mode, "last_run": time.time(), "regime": self.regime.get("state"), "profile": d["profile"]})
        if not s.get("start_ts") or s.get("halt") or s.get("pause") or time.time() - s.get("now", 0) > 600:
            bstate["status"] = "idle (plan not running or stale summary)"; jsave(st_dir / "brain.json", bstate); return False
        orders, notes = self.ratchet(d, s, self.regime.get("state"))
        new_buys = []
        if d["profile"] == "aggressive":
            o2, n2, new_buys = self.aggressive(d, s, st_dir, self.regime.get("state"), bstate)
            orders += o2; notes += n2
        elif d["profile"] == "fast":
            o2, n2, new_buys = self.fast(d, s, self.regime.get("state"), bstate)
            orders += o2; notes += n2
        elif d["profile"] == "traditional":
            o2, n2 = self.traditional(d, s, bstate)
            orders += o2; notes += n2
        bstate["status"] = "ok"
        if orders:
            now = time.time()
            did = f"auto-{key}-{time.strftime('%Y%m%d-%H%M', time.gmtime(now))}"
            title = L(d, "Cerebro automático: " + ("compra" if new_buys else "ajuste de stops" if all(o["action"] == "set" for o in orders) else "movimiento"),
                      "Automatic brain: " + ("new position" if new_buys else "stops raised" if all(o["action"] == "set" for o in orders) else "rebalance"))
            dec = {"id": did, "title": title, "journal": "\n\n".join(notes), "orders": orders, "auto": True}
            if mode == "live":
                jsave(st_dir / "auto" / f"{did}.json", dec)
                if new_buys:
                    today = time.strftime("%Y-%m-%d", time.localtime(now - 3 * 3600))
                    bstate.setdefault("auto_buys", []).extend({"day": today, "sym": b, "ts": now} for b in new_buys)
                    bstate["auto_buys"] = bstate["auto_buys"][-20:]
            with open(st_dir / "brain_shadow.jsonl", "a") as f:
                f.write(json.dumps({"ts": now, "mode": mode, **dec}, ensure_ascii=False) + "\n")
            bstate["last_action"] = {"ts": now, "title": title, "orders": len(orders), "mode": mode}
            log.info("[%s/%s] %s: %s", key, mode, title, [o["action"] + " " + (o.get("symbol") or o["mint"][:6]) for o in orders])
        elif notes:
            bstate["last_note"] = {"ts": time.time(), "text": notes[-1]}
        jsave(st_dir / "brain.json", bstate)
        return True

    def needs_candidates(self, modes):
        for key, d in DESKS.items():
            if d["profile"] != "aggressive" or modes.get(key) == "off":
                continue
            s = jload(paths(d)[1], {})
            if not s.get("start_ts"):
                continue
            eq_sol = s.get("equity_usd", 0) / (s.get("sol_usd") or 100)
            if s.get("cash_sol", 0) - 0.05 > eq_sol * LIM["idle_frac"] or any(time.time() - p.get("opened_ts", 0) > LIM["stale_h"] * 3600 for p in s.get("positions", [])):
                return True
        return False

    def cycle(self):
        modes = self.modes()
        self.update_regime()
        if self.regime.get("state") != "risk_off":
            self.refresh_candidates(self.needs_candidates(modes))
            self.refresh_fast(modes.get("agresivo", "off") != "off")
        for key, d in DESKS.items():
            if modes.get(key, "off") == "off":
                continue
            try:
                self.run_desk(key, d, modes[key])
            except Exception as e:  # noqa: BLE001
                log.exception("mesa %s: %s", key, e)

    def run(self, once=False):
        while True:
            t0 = time.time()
            try:
                self.cycle()
            except Exception as e:  # noqa: BLE001
                log.exception("ciclo: %s", e)
            if once:
                return
            time.sleep(max(30, 600 - (time.time() - t0)))


def main():
    from ..live.bot import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Brain(force_shadow="--shadow" in sys.argv).run(once="--once" in sys.argv)


if __name__ == "__main__":
    main()
