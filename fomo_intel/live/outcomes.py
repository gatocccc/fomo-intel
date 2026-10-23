"""Resultado a 6 h de TODOS los tokens que pasaron el primer corte en vivo (se movieron >= 3x al T2),
hayan sido operados o no. Es la muestra para aprender a separar rugs de ganadores.

Corre desde cron (server_sync.sh) cada 10 min:  python3 -m fomo_intel.live.outcomes
Lee state/signals.jsonl, baja las velas de 6 h (1 request por token, Solana Tracker) cuando el
token ya maduró, simula la salida v1.2 con stop realista y escribe state/outcomes.jsonl.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from ..backtest.entrysim import SimParams, simulate
from ..backtest.rules import V1
from ..charts import ChartFetcher
from .bot import load_dotenv

MATURE_S = 6.5 * 3600


def main(budget: int = 60) -> None:
    load_dotenv()
    state = Path(os.getenv("FOMO_STATE_DIR", "state"))
    data = os.getenv("FOMO_DATA_DIR", "data")
    sig_p, out_p = state / "signals.jsonl", state / "outcomes.jsonl"
    if not sig_p.exists():
        return
    done = set()
    if out_p.exists():
        for line in open(out_p):
            try: done.add(json.loads(line)["mint"])
            except Exception: pass  # noqa: BLE001
    now = time.time()
    rows = {}
    for line in open(sig_p):
        try: r = json.loads(line)
        except Exception: continue  # noqa: BLE001
        if r.get("move", 0) >= 3.0 and r["mint"] not in done and now - r["created_ts"] >= MATURE_S:
            rows[r["mint"]] = r            # la última fila por mint (la decisión final)
    if not rows:
        return
    cf = ChartFetcher(os.environ["SOLANATRACKER_API_KEY"], data)
    n = 0
    with open(out_p, "a") as out:
        for mint, r in list(rows.items())[:budget]:
            created = int(r["created_ts"])
            try:
                candles = cf.fetch(mint, created, hours=6.0)
            except Exception as e:  # noqa: BLE001
                print(f"{r.get('symbol')}: sin velas ({e})"); continue
            sim = simulate(mint, r.get("symbol", ""), created, candles, SimParams(entry_min=3, fill="close", stop_fill="close", **V1["exit"]))
            entry_px = sim.entry_px or 0
            last = candles[-1]["c"] if candles else 0
            peak = max((c["h"] for c in candles if c["t"] >= created + 180), default=0)
            o = {"ts": now, "mint": mint, "symbol": r.get("symbol"), "created_ts": created, "decision": r.get("decision"),
                 "passes_proxy": r.get("passes_proxy"), "passes": r.get("passes"), "reasons": r.get("reasons"),
                 "move": r.get("move"), "n_buyers_120s": r.get("n_buyers_120s"), "vol_usd": r.get("vol_usd"), "vol_per_buyer": r.get("vol_per_buyer"),
                 "n_snipers_st": r.get("n_snipers_st"), "n_snipers_proxy": r.get("n_snipers_proxy"), "risk_st": r.get("risk_st"),
                 "creator_prior_24h": r.get("creator_prior_24h"), "px_t3_vs_t2": r.get("px_t3_vs_t2"),
                 "entered": sim.entered, "ret_v12": sim.ret if sim.entered else None, "exits": [e[3] for e in sim.exits],
                 "peak_mult": round(peak / entry_px, 2) if entry_px else None,
                 "final_mult": round(last / entry_px, 3) if entry_px else None,
                 "rug": bool(entry_px and last < entry_px * 0.15), "n_candles": len(candles),
                 "last_candle_age_min": round((created + 6 * 3600 - candles[-1]["t"]) / 60) if candles else None}
            out.write(json.dumps(o) + "\n"); n += 1
    print(f"outcomes: {n} tokens evaluados, requests {cf.requests_made}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
