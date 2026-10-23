"""Generador de datos sintéticos para validar el pipeline sin API keys.

Reproduce tres arquetipos observados en la realidad:
  - 'anglio'  : front-runner. 3 side wallets fondeadas desde la pública compran ~20 s antes
                del call, venden ~4 min después en el pico, depositan en la misma CEX.
  - 'conviccion': cluster y pública compran juntos y holdean; el token tiende a subir.
  - 'copybot' : ruido. Wallets que compran SIEMPRE después de la pública (no deben
                entrar al cluster).
Los precios siguen un camino que depende del arquetipo: pump de 4 min y colapso para el
front-runner, deriva positiva ruidosa para convicción.
"""
from __future__ import annotations

import random

from .models import Trade, Transfer, WalletLabel
from .sources.store import Store


def _w(rng: random.Random, prefix: str) -> str:
    return prefix + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz123456789") for _ in range(38))


def _price_path(rng: random.Random, p0: float, t0: int, kind: str, horizon: int = 3 * 86400) -> list[tuple[int, float]]:
    path, p, t = [], p0, t0
    step = 20
    while t <= t0 + horizon:
        rel = t - t0
        if kind == "frontrun":
            if rel < 240:
                drift = 0.08              # pump por la ola de copiadores (~+150% en 4 min)
            elif rel < 1200:
                drift = -0.03             # colapso por la distribución
            else:
                drift = -0.0002
            vol = 0.02
        else:  # conviccion
            drift, vol = (0.004 if rel < 1800 else 0.0001), 0.012
        p = max(p0 * 0.05, p * (1 + drift + rng.gauss(0, vol)))
        path.append((t, p))
        t += step
        if rel > 3600:
            step = 300
    return path


def generate(store: Store, seed: int = 7, n_calls: int = 25) -> dict:
    rng = random.Random(seed)
    cex = "CEXdepositAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    store.labels[cex] = WalletLabel(cex, "exchange_deposit", "Binance deposit #1")
    t = 1_760_000_000
    archetypes = {
        "anglio_like": {"kind": "frontrun", "public": _w(rng, "PUB1"), "sides": [_w(rng, "SIDE") for _ in range(3)]},
        "conviction_like": {"kind": "conviccion", "public": _w(rng, "PUB2"), "sides": [_w(rng, "SIDE") for _ in range(2)]},
    }
    copybots = [_w(rng, "BOT") for _ in range(4)]
    truth = {}
    for name, a in archetypes.items():
        truth[name] = {"public": a["public"], "sides": a["sides"]}
        # fondeo de side wallets desde la pública + depósito común en CEX
        for s in a["sides"]:
            store.add_transfers([Transfer(a["public"], s, rng.uniform(800, 3000), t - 86400 * 20, f"fund_{s[:6]}")])
            store.add_transfers([Transfer(s, cex, rng.uniform(500, 2000), t + 86400 * 40, f"dep_{s[:6]}")])
        store.add_transfers([Transfer(a["public"], cex, 5000, t + 86400 * 41, f"dep_{a['public'][:6]}")])

    for i in range(n_calls):
        for name, a in archetypes.items():
            token = _w(rng, "TOK")
            t_call = t + i * 86400 * 2 + rng.randint(0, 40_000)
            p0 = rng.uniform(1e-6, 1e-4)
            path = _price_path(rng, p0, t_call - 60, a["kind"])
            store.prices[token] = path
            store.token_meta[token] = {"liquidity_usd": rng.uniform(60_000, 400_000), "created_ts": t_call - 86400 * rng.randint(2, 30)}
            # side wallets: compran antes (front-run) o casi a la vez (convicción)
            for s in a["sides"]:
                lead = rng.randint(10, 35) if a["kind"] == "frontrun" else rng.randint(-20, 40)
                ts_b = t_call - lead
                usd = rng.uniform(300, 1500)
                price = next((p for pts, p in path if pts >= ts_b), p0)
                store.add_trades([Trade(s, token, "buy", usd, usd / price, ts_b, f"sb_{s[:5]}_{i}", price_usd=price)])
            # pública
            price = next((p for pts, p in path if pts >= t_call), p0)
            usd = rng.uniform(2000, 8000)
            store.add_trades([Trade(a["public"], token, "buy", usd, usd / price, t_call, f"pb_{a['public'][:5]}_{i}", price_usd=price)])
            # copybots: siempre 2-15 s después
            for b in copybots:
                ts_b = t_call + rng.randint(2, 15)
                price = next((p for pts, p in path if pts >= ts_b), p0)
                store.add_trades([Trade(b, token, "buy", 200, 200 / price, ts_b, f"bot_{b[:5]}_{i}", price_usd=price)])
            if a["kind"] == "frontrun":
                for s in a["sides"]:
                    ts_s = t_call + rng.randint(200, 300)
                    price = next((p for pts, p in path if pts >= ts_s), p0)
                    qty = next(tr.token_amount for tr in store.trades if tr.wallet == s and tr.token == token)
                    store.add_trades([Trade(s, token, "sell", qty * price, qty, ts_s, f"ss_{s[:5]}_{i}", price_usd=price)])
                ts_s = t_call + 400
                price = next((p for pts, p in path if pts >= ts_s), p0)
                qty = next(tr.token_amount for tr in store.trades if tr.wallet == a["public"] and tr.token == token)
                store.add_trades([Trade(a["public"], token, "sell", qty * price, qty, ts_s, f"ps_{a['public'][:5]}_{i}", price_usd=price)])
            else:
                # convicción: venta parcial coordinada a los 2 días
                for w in a["sides"] + [a["public"]]:
                    ts_s = t_call + 86400 * 2
                    price = store.price_at(token, ts_s) or p0
                    qty = next(tr.token_amount for tr in store.trades if tr.wallet == w and tr.token == token) * 0.3
                    store.add_trades([Trade(w, token, "sell", qty * price, qty, ts_s, f"cs_{w[:5]}_{i}", price_usd=price)])
    truth["copybots"] = copybots
    store.save()
    return truth
