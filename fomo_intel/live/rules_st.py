"""Estrategia v1.2 en vivo sobre TODOS los lanzamientos, sin pagar trades a PumpPortal.

- Lanzamientos: PumpPortal subscribeNewToken (gratis).
- Al T2 (misma definición de reloj que el backtest): precio de muchos tokens en 1 request
  (Solana Tracker /price/multi). Los que se movieron >= min_move siguen; el resto se descarta.
- Para los que siguen: velas 1m (1 req), token + riesgo (1 req), primeros compradores (1 req) ->
  `features()` y `rule_v11()` EXACTAMENTE como en la validación; al T3, velas otra vez (1 req) y
  `confirmed()`. Entrada al cierre del T3 con cotización real del swap (paper) o compra real.
- Precio de las posiciones abiertas: PumpPortal por token (pocos tokens: centavos) con respaldo en /price.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict

import requests

from ..backtest.rules import V1, build_context, confirmed, features, rule_v11
from ..charts import ChartFetcher
from ..launches import LaunchFetcher
from .signals import t2_of, t3_of

log = logging.getLogger("live.rules_st")
ST_BASE = "https://data.solanatracker.io"
BASE_PRICE_SOL = 30.0 / 1_073_000_000.0


class RulesST:
    def __init__(self, bot):
        self.bot = bot
        self.p = bot.p
        self.h = {"x-api-key": bot.env.solanatracker_api_key}
        self.lf = LaunchFetcher(bot.env.solanatracker_api_key, str(bot.env.data_dir), sleep_s=0.0)
        self.cf = ChartFetcher(bot.env.solanatracker_api_key, str(bot.env.data_dir), sleep_s=0.0)
        self.launches = {L.mint: L for L in self.lf.load_all()}
        self.ctx = build_context(self.launches)
        self.pending_t3: dict[str, dict] = {}     # mint -> {L, f, created}
        self.evaluated: set[str] = set()
        self.last_multi = 0.0
        self.stats = {"multi_calls": 0, "prefilter_pass": 0, "full_eval": 0, "candidates": 0, "bought": 0}

    def requests_made(self) -> int:
        return self.lf.requests_made + self.cf.requests_made + self.stats["multi_calls"]

    # ---------- precios en lote ----------
    def _multi_price(self, mints: list[str]) -> dict:
        out = {}
        for i in range(0, len(mints), 100):
            chunk = mints[i:i + 100]
            self.stats["multi_calls"] += 1
            try:
                r = requests.get(f"{ST_BASE}/price/multi", headers=self.h, params={"tokens": ",".join(chunk)}, timeout=20)
                if r.status_code == 404 or r.status_code == 405:
                    r = requests.post(f"{ST_BASE}/price/multi", headers=self.h, json={"tokens": chunk}, timeout=20)
                r.raise_for_status()
                d = r.json()
                out.update(d if isinstance(d, dict) else {})
            except Exception as e:  # noqa: BLE001
                log.warning("price/multi: %s", e)
        return out

    # ---------- paso 1: T2 ----------
    def step_t2(self, now: float) -> None:
        if now - self.last_multi < 45:
            return
        self.last_multi = now
        due = [st for st in self.bot.stream.young(60, 900)
               if st.mint not in self.evaluated and now >= t2_of(st.created_ts, self.p.eval_min) and st.pool == "pump"]
        if not due:
            return
        for st in due:
            self.evaluated.add(st.mint)
        prices = self._multi_price([st.mint for st in due])
        sol_usd = self.bot.sol_usd or 1.0
        base_usd = BASE_PRICE_SOL * sol_usd
        for st in due:
            info = prices.get(st.mint) or {}
            px = float(info.get("price") or 0)
            if px <= 0:
                continue
            move = px / base_usd
            if move < self.p.min_move or move > self.p.max_move * 3:
                continue
            self.stats["prefilter_pass"] += 1
            self._full_eval(st, now)

    def _full_eval(self, st, now: float) -> None:
        mint, created = st.mint, int(st.created_ts)
        try:
            candles = self.cf.fetch(mint, created, hours=(now - created) / 3600 + 0.05, force=True)
            L = self.lf.fetch_launch(mint, None, cheap=True)
            if not L:
                return
            if L.created_ts <= 0:
                L.created_ts = created
            L = self.lf.complete_buyers(L)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: evaluación falló (%s)", st.symbol, e); return
        self.stats["full_eval"] += 1
        self.launches[mint] = L
        self.ctx = build_context(self.launches) if len(self.launches) % 50 == 0 else self.ctx
        self.ctx["by_symbol"].setdefault(L.symbol.strip().lower(), []).append((L.created_ts, L.mint))
        if L.deployer:
            self.ctx["by_dev"].setdefault(L.deployer, []).append((L.created_ts, L.graduated))
        f = features(L, candles, self.ctx, V1["entry_min"])
        d = {"mint": mint, "symbol": L.symbol or st.symbol, "created_ts": L.created_ts, "strategy": "rules_st",
             "move": round(f["move_vs_base"] or 0, 2), "n_buyers_120s": f["n_buyers_entry"], "n_buyers_60s": f["n_buyers_60s"],
             "vol_usd": f["vol_usd_entry"], "vol_per_buyer": round(f["vol_usd_entry"] / max(1, f["n_buyers_entry"]), 1),
             "n_snipers_st": f["n_snipers"], "sniper_pct": f["sniper_pct"], "n_bundlers": f["n_bundlers"], "dev_in_first10": f["dev_in_first10"],
             "prior_dev_launches": f["prior_dev_launches"], "rugged_st": L.rugged, "risk_score": L.risk_score, "top10_pct": L.top10_pct, "dev_pct": L.dev_pct,
             "insider_pct": L.insider_pct, "bundler_pct": L.bundler_pct, "holders": L.holders, "liq_usd": L.liquidity_usd, "mcap_usd": L.market_cap_usd,
             "early_buyers": [[b.wallet, round(b.invested_usd, 2), b.first_trade_ts - L.created_ts] for b in sorted(L.first_buyers, key=lambda b: b.first_trade_ts) if 0 <= b.first_trade_ts - L.created_ts <= 120][:150],
             "passes_proxy": True, "passes": bool(rule_v11(f)), "t3": t3_of(L.created_ts, self.p.entry_min)}
        if not d["passes"]:
            self.bot.port.log_signal(d, "descartado_v12"); return
        self.stats["candidates"] += 1
        self.pending_t3[mint] = {"L": L, "d": d, "px_t2": f["entry_px"]}
        log.info("CANDIDATO v1.2 %s move=%.1fx compradores=%d vol=$%.0f snipers=%d -> confirma a T3", d["symbol"], d["move"], d["n_buyers_120s"], d["vol_usd"], d["n_snipers_st"])

    # ---------- paso 2: T3 ----------
    def step_t3(self, now: float) -> None:
        for mint, c in list(self.pending_t3.items()):
            d = c["d"]
            if now < d["t3"] + 5:            # 5 s de margen para que exista la vela
                continue
            self.pending_t3.pop(mint)
            L = c["L"]
            try:
                candles = self.cf.fetch(mint, int(L.created_ts), hours=(now - L.created_ts) / 3600 + 0.05, force=True)
            except Exception as e:  # noqa: BLE001
                self.bot.port.log_signal(d, f"sin velas en T3: {e}"); continue
            ok = confirmed(candles, L.created_ts, self.p.entry_min, self.p.confirm_tol)
            c3 = [x for x in candles if x["t"] >= int(L.created_ts) + self.p.entry_min * 60]
            px3_usd = c3[0]["c"] if c3 else 0
            d["px_t3_vs_t2"] = round(px3_usd / c["px_t2"], 3) if c["px_t2"] else None
            if not ok:
                self.bot.port.log_signal(d, "no_confirmado"); continue
            self.bot.enter_from_rules(mint, d, px3_usd)

    def step(self, now: float) -> None:
        self.step_t2(now)
        self.step_t3(now)
