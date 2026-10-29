"""El libro único ("Lloyd") para la app: vista pública, expectativas por nivel de riesgo y bitácora de investigación.

- /api/book: lee state/plan_lloyd_summary.json (lo escribe el motor cada 30 s) y state/plan_lloyd/book.json (lo escribe el cerebro:
  régimen y bolsillos). Mientras no exista el libro (antes de la migración), arma la misma vista sumando los tres planes.
- /api/expect: en vez de "probabilidad de x2 en 30 días", lo que un usuario puede esperar según su dial de riesgo: rango de
  resultados a 30 y 90 días y probabilidad de tocar su límite. Simula caminos con los resultados reales del libro (todas las
  operaciones cerradas de la casa) mezclados con supuestos iniciales mientras haya pocas; lo dice.
- Bitácora de investigación: state/research/ledger.json (lo que se probó, cómo, qué dio y si entró o no al bot).
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

STATE = Path(os.getenv("FOMO_STATE_DIR", "state"))
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
STABLES = {USDC, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
MAJORS = {"cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij", "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"}
SLEEVES = [("cash", "Cash"), ("majors", "Majors"), ("established", "Established memes"), ("picks", "Picks")]
LEGACY = (("agresivo", "picks"), ("equilibrado", "established"), ("tradicional", "majors"))

# Dial de riesgo: caída máxima que el usuario acepta ver → qué parte de su depósito sigue al libro (el resto queda en USDC) y qué tan
# corto se le corta. El libro entero, con sus stops, apunta a una caída máxima del orden de 35%: el nivel "regular" lo sigue entero.
RISK_LEVELS = [
    {"pct": 20, "key": "quiet", "name": "Quiet corner", "exposure_pct": 55,
     "blurb": "A little more than half of your deposit follows the book; the rest waits in USDC. The slowest ride, the smallest swings."},
    {"pct": 35, "key": "regular", "name": "Regular's stool", "exposure_pct": 100,
     "blurb": "Your deposit follows the book as it is: four pockets, stops that only move up, cash when nothing passes the filters."},
    {"pct": 50, "key": "loud", "name": "Loud table", "exposure_pct": 100,
     "blurb": "Follows the book with wider stops on the Picks pocket, so winners get more room and losers cost more. Only for money you can lose."},
]
PROFIT_RULES = [{"key": "run", "name": "Let it run"}, {"key": "lock", "name": "Lock in at a multiple"}, {"key": "sweep", "name": "Sweep profits monthly"}]


def jl(p, d=None):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def sleeve_of(p: dict) -> str:
    if p.get("sleeve"):
        return p["sleeve"]
    if p.get("mint") in STABLES:
        return "cash"
    if p.get("mint") in MAJORS:
        return "majors"
    return "picks"


def _legacy_summary() -> dict | None:
    """Antes de la migración: los tres planes sumados como si fueran un libro."""
    parts = [(jl(STATE / f"plan_{k}_summary.json"), sl) for k, sl in LEGACY]
    parts = [(d, sl) for d, sl in parts if d and d.get("start_ts")]
    if not parts:
        return None
    base = dict(parts[0][0])
    base.update({"equity_usd": sum(d["equity_usd"] for d, _ in parts), "start_usd": round(sum(d["start_usd"] for d, _ in parts), 2),
                 "cash_sol": sum(d.get("cash_sol", 0) for d, _ in parts), "start_ts": min(d["start_ts"] for d, _ in parts),
                 "positions": [dict(p, sleeve=p.get("sleeve") or ("cash" if p.get("mint") in STABLES else sl)) for d, sl in parts for p in d.get("positions", [])],
                 "closed": sorted([dict(c, sleeve=sl) for d, sl in parts for c in d.get("closed", [])], key=lambda c: -c.get("ts", 0)),
                 "journal": sorted([j for d, _ in parts for j in d.get("journal", [])], key=lambda j: -j.get("ts", 0))[:80],
                 "equity": sorted([e for d, _ in parts for e in d.get("equity", [])])[-400:],
                 "n_closed": sum(d.get("n_closed", 0) for d, _ in parts), "wins": sum(d.get("wins", 0) for d, _ in parts),
                 "realized_usd": round(sum(d.get("realized_usd", 0) for d, _ in parts), 2), "legacy": True})
    return base


def _summary() -> dict | None:
    d = jl(STATE / "plan_lloyd_summary.json")
    if d and d.get("start_ts"):
        return d
    return _legacy_summary()


def max_drawdown(eq: list) -> float:
    peak = None; dd = 0.0
    for _, v in eq:
        peak = v if peak is None else max(peak, v)
        if peak:
            dd = max(dd, 1 - v / peak)
    return round(dd * 100, 1)


def book_view(full: bool = True, admin: bool = False) -> dict | None:
    s = _summary()
    if not s:
        return None
    bk = jl(STATE / "plan_lloyd" / "book.json", {}) or {}
    rg = bk.get("regime") or jl(STATE / "desk" / "regime.json", {}) or {}
    br = s.get("brain") or {}
    eq = s.get("equity_usd") or 0; start = s.get("start_usd") or 0; sol_usd = s.get("sol_usd") or 100
    pos = s.get("positions") or []
    free_sol_usd = max(0.0, (s.get("cash_sol") or 0) - 0.08) * sol_usd
    val = {k: 0.0 for k, _ in SLEEVES}; cnt = {k: 0 for k, _ in SLEEVES}
    for p in pos:
        k = sleeve_of(p); val[k] += p.get("value_usd") or 0
        if p.get("mint") not in STABLES:
            cnt[k] += 1
    val["cash"] += free_sol_usd
    budgets = bk.get("budgets") or {}
    sleeves = [{"key": k, "name": n, "target_pct": round((budgets.get(k) or 0) * 100) if budgets else None, "value_usd": round(val[k], 2),
                "pct": round(val[k] / eq * 100, 1) if eq else 0, "positions": cnt[k]} for k, n in SLEEVES]
    closed = s.get("closed") or []
    rets = [(c.get("symbol"), c.get("ret")) for c in closed if c.get("ret") is not None]
    out = {"name": "Lloyd", "wallet": s.get("wallet"), "since": s.get("start_ts"), "start_usd": start, "equity_usd": eq,
           "pnl_usd": round(eq - start, 2) if start else None, "pnl_pct": round(eq / start - 1, 4) if start else None,
           "cash_usd": round(val["cash"], 2), "updated": s.get("now"), "legacy": bool(s.get("legacy")),
           "regime": {"state": rg.get("state", "neutral"), "label": rg.get("label") or {"risk_on": "constructive", "neutral": "neutral", "risk_off": "defensive"}.get(rg.get("state"), "neutral"),
                      "sol_vs_ma20": round(rg["sol"] / rg["sol_ma20"] - 1, 4) if rg.get("sol_ma20") else None, "btc_vs_ma20": rg.get("btc_vs_ma20"),
                      "breadth": {"above": rg["breadth_above"], "total": rg["breadth_total"]} if rg.get("breadth_total") else None,
                      "sol_24h": rg.get("sol_ch24h"), "since": rg.get("since")},
           "sleeves": sleeves,
           "positions": [{"token": p.get("symbol"), "sleeve": sleeve_of(p), "multiple": p.get("mult"), "value_usd": p.get("value_usd"),
                          "stop_mult": round(1 - float(p.get("stop", 0)), 3) if p.get("stop") is not None and p.get("mint") not in STABLES else None,
                          "opened": p.get("opened_ts"), "thesis": p.get("thesis")} for p in pos if p.get("mint") not in STABLES],
           "stats": {"closed": s.get("n_closed", len(closed)), "wins": s.get("wins"), "realized_usd": s.get("realized_usd"),
                     "max_drawdown_pct": max_drawdown(s.get("equity") or []),
                     "best": {"token": max(rets, key=lambda x: x[1])[0], "result": max(rets, key=lambda x: x[1])[1]} if rets else None,
                     "worst": {"token": min(rets, key=lambda x: x[1])[0], "result": min(rets, key=lambda x: x[1])[1]} if rets else None},
           "brain": {"last_run": br.get("last_run"), "every_min": 10, "last_action": br.get("last_action"), "next_review": "09:39 / 21:39 ART",
                     "live": br.get("mode") == "live"}}
    if full:
        out["closed_list"] = [{"ts": c.get("ts"), "token": c.get("symbol"), "sleeve": c.get("sleeve") or "picks", "result": c.get("ret"), "pnl_usd": c.get("pnl_usd"),
                               "why": c.get("why"), "hold_h": c.get("hold_h")} for c in closed[:40]]
        out["journal"] = [{"ts": j.get("ts"), "title": j.get("title"), "text": j.get("text"), "kind": j.get("kind")} for j in (s.get("journal") or [])[:60]]
        out["equity"] = (s.get("equity") or [])[-500:]
    if admin:
        out["sleeve_budgets"] = budgets
        out["brain_detail"] = {k: v for k, v in br.items()} | {"book_ts": bk.get("ts"), "liquid_usd": bk.get("liquid_usd"), "trad_status": bk.get("trad_status")}
        out["wallet_sol"] = s.get("cash_sol")
    return out


# ---------------------------------------------------------------- expectativas
PRIOR = {"win": 0.42, "up": 0.28, "down": -0.20, "spread": 0.7, "frac": 0.22, "per_day": 0.8}   # supuesto inicial neutro: sin ventaja hasta que los datos digan otra cosa
MIN_REAL = 30


def _real_returns() -> list[float]:
    out = []
    for d in ("plan_lloyd", "plan_agresivo", "plan_equilibrado", "plan_tradicional", "desk"):
        f = STATE / d / "closed.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line).get("ret")
                if r is not None:
                    out.append(float(r))
            except Exception:  # noqa: BLE001
                pass
    return out


def expect(risk_pct: int, paths: int = 3000) -> dict:
    lvl = next((r for r in RISK_LEVELS if r["pct"] == int(risk_pct)), RISK_LEVELS[1])
    real = _real_returns()
    expo = lvl["exposure_pct"] / 100
    wider = 1.25 if lvl["key"] == "loud" else 1.0
    out = {"risk": lvl["pct"], "key": lvl["key"], "name": lvl["name"], "exposure_pct": lvl["exposure_pct"], "horizons": [],
           "based_on_trades": len(real), "preliminary": len(real) < MIN_REAL}
    for days in (30, 90):
        n = max(1, round(PRIOR["per_day"] * days))
        finals, hit = [], 0
        for i in range(paths):
            rng = random.Random(11 * 1_000_003 + i)
            e, peak, touched = 1.0, 1.0, False
            for _ in range(n):
                if real and rng.random() < len(real) / (len(real) + MIN_REAL):
                    r = rng.choice(real)
                else:
                    base = PRIOR["up"] if rng.random() < PRIOR["win"] else PRIOR["down"]
                    r = base * (1 + rng.gauss(0, PRIOR["spread"]))
                    r = max(r, 0.0) if base > 0 else max(min(r, 0.0), -0.95)
                r = r * wider if r < 0 else r * (1 + (wider - 1) * 1.6)
                e *= 1 + expo * PRIOR["frac"] * r
                peak = max(peak, e)
                if 1 - e / peak >= lvl["pct"] / 100:
                    touched = True
            finals.append(e); hit += touched
        finals.sort()
        out["horizons"].append({"days": days, "median_mult": round(finals[len(finals) // 2], 3), "p10_mult": round(finals[len(finals) // 10], 3),
                                "p90_mult": round(finals[len(finals) * 9 // 10], 3), "prob_hit_limit": round(hit / paths, 3)})
    out["note"] = (f"Preliminary: built from {len(real)} real trades of the house book plus starting assumptions; it recalculates as Lloyd trades."
                   if out["preliminary"] else f"Built from {len(real)} real trades of the house book.")
    return out


# ---------------------------------------------------------------- investigación
RESEARCH = STATE / "research" / "ledger.json"
SEED = [
    {"date": "2026-10-23", "name": "Copying FOMO app traders", "question": "Can we front-run or copy the best FOMO app wallets?", "method": "On-chain audit of 60+ wallets, 7-day forward test",
     "result": "Winners churn; copying after the fact loses to fees and slippage.", "verdict": "rejected"},
    {"date": "2026-10-25", "name": "Technical signals on liquid memecoins", "question": "Does any TA entry beat random in 27 liquid memecoins?", "method": "90 days, out-of-sample half, random-entry control",
     "result": "Every strategy lost 2–5% per trade; none beat random.", "verdict": "rejected"},
    {"date": "2026-10-26", "name": "Tweet sniper on fresh launches", "question": "Do influencer tweets predict pumps early enough to buy?", "method": "Dataset of tweets vs. 6h outcomes, shadow run",
     "result": "Signals arrive after the move; snipers own the first minutes.", "verdict": "rejected"},
    {"date": "2026-10-27", "name": "Anti-rug: common-funder clustering", "question": "Can we detect rugs by tracing who funded the top holders?", "method": "Helius funded-by on top-20 holders + deployer history, applied live",
     "result": "Caught 3 concentrated tokens before buying (CHICO, tSpaceX, LMAO!).", "verdict": "adopted"},
    {"date": "2026-10-28", "name": "Perps signals on Hyperliquid", "question": "Any short-term long/short edge in perps (funding, cascades, breakouts, pairs)?", "method": "34 markets, 90 days, real funding, out-of-sample, random control",
     "result": "None passed (t ≥ 2.5 and beat random). Volume breakouts lose clearly (−1.5%/trade).", "verdict": "rejected"},
    {"date": "2026-10-28", "name": "Fast momentum in $300K–3M memecoins", "question": "Does buying small caps already up 100%+ 'on a pullback' work with 12h time stops?", "method": "Live, two trades",
     "result": "Both stopped out within an hour (−26%, −28%). Turned off the same night.", "verdict": "rejected"},
    {"date": "2026-10-28", "name": "Stops that only move up", "question": "Does ratcheting the stop with the peak keep more of the winners?", "method": "Live on GTA6/REMUS; rules 1.3x→entry, 1.6x→75% of peak",
     "result": "REMUS closed +14% instead of round-tripping; GTA6 protected at 1.3x.", "verdict": "adopted"},
]


def research() -> dict:
    d = jl(RESEARCH, None)
    if not d:
        RESEARCH.parent.mkdir(parents=True, exist_ok=True)
        d = {"experiments": SEED}
        json.dump(d, open(RESEARCH, "w"), indent=1, ensure_ascii=False)
    exps = sorted(d.get("experiments", []), key=lambda e: e.get("date", ""), reverse=True)
    return {"experiments": exps, "next_run": "Weekly: Sunday 09:39 ART review re-runs the backtests with the new week of data.", "updated": time.time()}
