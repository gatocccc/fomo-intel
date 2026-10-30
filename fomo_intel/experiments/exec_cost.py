"""Auditoría de costos de ejecución (bitácora: "Execution cost audit + MEV protection", 30/10).

Pregunta: de lo que nos cuesta cada operación de memecoin, ¿cuánto es precio de mercado movido (impacto + comisión)
y cuánto se lo llevan bots que nos hacen "sándwich" (compran justo antes y venden justo después en el mismo bloque)?

Método, sobre NUESTRAS operaciones reales (state/plan_*/trades.jsonl + state/trades.jsonl):
 1. Costo realizado por operación = precio que obtuvimos vs. precio de mercado del minuto anterior (vela 1m de Solana Tracker).
    compra: fill/mid - 1 ; venta: 1 - fill/mid. Positivo = pagamos.
 2. Sándwich: getTransaction(sig) -> slot e índice; getBlock(slot, accounts) -> en el mismo bloque, ¿hay un firmante que
    toca el mismo token ANTES y DESPUÉS de nuestra transacción? (front-run + back-run). Se cuentan también los casos en que
    sólo hay alguien justo antes (front-run sin cierre en el bloque).
Salida: tabla por operación y resumen por tipo (memecoin compra/venta; pases a USDC), JSON en state/research/exec_cost.json.
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import time
from pathlib import Path

import requests

ST = "https://data.solanatracker.io"
STK = os.getenv("SOLANATRACKER_API_KEY", "")
HK = os.getenv("HELIUS_API_KEY", "")
RPC = f"https://mainnet.helius-rpc.com/?api-key={HK}" if HK else "https://api.mainnet-beta.solana.com"
STABLE = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
SOL = "So11111111111111111111111111111111111111112"
SKIP_ACC = {SOL, "11111111111111111111111111111111", "ComputeBudget111111111111111111111111111111",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
            "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}


def rpc(method, params):
    for i in range(4):
        try:
            r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=40)
            if r.status_code == 429:
                time.sleep(2 * (i + 1)); continue
            return r.json().get("result")
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def mid_before(mint, ts):
    try:
        r = requests.get(f"{ST}/chart/{mint}", headers={"x-api-key": STK},
                         params={"type": "1m", "time_from": int(ts) - 600, "time_to": int(ts) + 120}, timeout=30)
        cs = r.json().get("oclhv", [])
        time.sleep(0.4)
    except Exception:  # noqa: BLE001
        return None, None
    before = [c for c in cs if int(c["time"]) + 60 <= ts]
    at = [c for c in cs if int(c["time"]) <= ts < int(c["time"]) + 60]
    m = float(before[-1]["close"]) if before else None
    a = float(at[0]["close"]) if at else None
    return m, a


def keys_of(tx):
    msg = (tx.get("transaction") or {})
    acc = msg.get("accountKeys") or (msg.get("message") or {}).get("accountKeys") or []
    out = []
    for a in acc:
        out.append(a["pubkey"] if isinstance(a, dict) else a)
    signer = None
    for a in acc:
        if isinstance(a, dict) and a.get("signer"):
            signer = a["pubkey"]; break
    if signer is None and out:
        signer = out[0]
    return set(out), signer


def sandwich(sig, mint, me):
    t = rpc("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
    if not t:
        return {"checked": False}
    slot = t["slot"]
    b = rpc("getBlock", [slot, {"encoding": "json", "transactionDetails": "accounts", "maxSupportedTransactionVersion": 1,
                               "rewards": False, "commitment": "confirmed"}])
    if not b:
        return {"checked": False, "slot": slot}
    txs = b.get("transactions") or []
    idx = None
    for i, x in enumerate(txs):
        if sig in ((x.get("transaction") or {}).get("signatures") or []):
            idx = i; break
    if idx is None:
        return {"checked": False, "slot": slot}
    my_keys, _ = keys_of(txs[idx])
    pool_keys = my_keys - SKIP_ACC - {me}
    before, after = {}, {}
    for i, x in enumerate(txs):
        if i == idx or (x.get("meta") or {}).get("err"):
            continue
        ks, signer = keys_of(x)
        if mint not in ks or signer == me:
            continue
        shared = len(ks & pool_keys)
        if shared < 3:
            continue
        (before if i < idx else after).setdefault(signer, []).append(i)
    both = sorted(set(before) & set(after))
    near_before = [s for s, ii in before.items() if max(ii) >= idx - 3]
    return {"checked": True, "slot": slot, "idx": idx, "n_block": len(txs), "same_pool_before": len(before),
            "same_pool_after": len(after), "sandwich_signers": both[:3], "front_run_close": len(near_before)}


def main():
    rows, seen = [], set()
    for f in sorted(glob.glob("state/plan_*/trades.jsonl")) + ["state/trades.jsonl"]:
        if not Path(f).exists():
            continue
        for line in open(f):
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if not d.get("ok") or d.get("side") not in ("buy", "sell") or not d.get("sig") or d["sig"] in seen:
                continue
            seen.add(d["sig"]); d["_file"] = f; rows.append(d)
    wallets = {}
    for f in glob.glob("state/plan_*_summary.json"):
        try:
            s = json.load(open(f)); wallets[f.split("plan_")[1].split("_summary")[0]] = s.get("wallet")
        except Exception:  # noqa: BLE001
            pass
    out = []
    for d in sorted(rows, key=lambda r: r["ts"]):
        mint = d["mint"]; px = d.get("price_usd")
        kind = "stable" if mint in STABLE else "meme"
        mid, at = (None, None)
        if kind == "meme" and px:
            mid, at = mid_before(mint, d["ts"])
        cost = None
        if mid and px:
            cost = (px / mid - 1) * 100 if d["side"] == "buy" else (1 - px / mid) * 100
        plan = d["_file"].split("plan_")[1].split("/")[0] if "plan_" in d["_file"] else "root"
        me = wallets.get(plan)
        sw = sandwich(d["sig"], mint, me) if kind == "meme" else {"checked": False}
        r = {"ts": int(d["ts"]), "plan": plan, "side": d["side"], "symbol": d.get("symbol"), "kind": kind, "sol": round(d.get("sol") or 0, 4),
             "slip_logged": d.get("slip"), "cost_vs_1m_mid": round(cost, 2) if cost is not None else None,
             "cost_vs_same_min_close": round(((px / at - 1) if d["side"] == "buy" else (1 - px / at)) * 100, 2) if (at and px) else None, **sw}
        out.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    summ = {}
    for kind in ("meme", "stable"):
        for side in ("buy", "sell"):
            g = [r for r in out if r["kind"] == kind and r["side"] == side]
            c = [r["cost_vs_1m_mid"] for r in g if r["cost_vs_1m_mid"] is not None]
            sl = [r["slip_logged"] for r in g if r["slip_logged"] is not None]
            chk = [r for r in g if r.get("checked")]
            summ[f"{kind}_{side}"] = {"n": len(g), "cost_mean": round(st.mean(c), 2) if c else None, "cost_median": round(st.median(c), 2) if c else None,
                                      "slip_logged_mean": round(st.mean(sl), 2) if sl else None, "checked_blocks": len(chk),
                                      "sandwiched": sum(1 for r in chk if r["sandwich_signers"]),
                                      "front_run_close": sum(1 for r in chk if r["front_run_close"])}
    # A/B de ruta (desde 30/10): costo por vía en memecoins
    via_of = {d["sig"]: (d.get("ab_arm") or d.get("via")) for d in rows}
    for r, d in zip(out, sorted(rows, key=lambda r: r["ts"])):
        r["via"] = via_of.get(d["sig"])
    for arm in ("jupiter", "solanatracker", "pumpportal"):
        for side in ("buy", "sell"):
            c = [r["cost_vs_1m_mid"] for r in out if r["kind"] == "meme" and r["side"] == side and r.get("via") == arm and r["cost_vs_1m_mid"] is not None]
            if c:
                summ[f"ab_{arm}_{side}"] = {"n": len(c), "cost_mean": round(st.mean(c), 2), "cost_median": round(st.median(c), 2)}
    print("\nRESUMEN", json.dumps(summ, ensure_ascii=False, indent=1))
    Path("state/research").mkdir(parents=True, exist_ok=True)
    json.dump({"rows": out, "summary": summ, "ts": int(time.time())}, open("state/research/exec_cost.json", "w"), indent=1)


if __name__ == "__main__":
    main()
