"""¿Qué hace comprar a decu? Para cada compra grande reciente (>= MIN_SOL) reconstruye lo que era visible ANTES de su compra:
creador (y quién lo fondeó), compra inicial del dev, quiénes compraron antes y cuánto, segundos/slots desde la creación,
metadatos (nombre, redes, link de X, host de la imagen = herramienta de lanzamiento) y el resultado de decu en ese token.

Busca repeticiones: mismos creadores, mismos fondeadores, mismas billeteras que compran antes que él, mismas cuentas de X.
Uso: python -m fomo_intel.experiments.decu_triggers [N_TOKENS] [HORAS]   -> state/decu_triggers.json + resumen en stdout.
"""
from __future__ import annotations

import json
import os
import statistics as stt
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from ..live.helius_watch import decode_trades_from_logs

W = "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"
SOL = "So11111111111111111111111111111111111111112"
ST = "https://data.solanatracker.io"
STH = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
RPC = os.environ.get("SOLANA_RPC_URL") or f"https://mainnet.helius-rpc.com/?api-key={os.environ.get('HELIUS_API_KEY', '')}"
MIN_SOL = 1.0
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def st_get(path, **p):
    for i in range(4):
        try:
            r = requests.get(ST + path, headers=STH, params=p, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 * (i + 1)); continue
            return None
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return None


def rpc(method, params):
    for i in range(6):
        try:
            r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
            if r.status_code == 429:
                time.sleep(0.5 * (i + 1)); continue
            j = r.json()
            if "error" in j:
                if "429" in str(j["error"]) or "rate" in str(j["error"]).lower():
                    time.sleep(0.5 * (i + 1)); continue
                return None
            return j.get("result")
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def get_tx(sig):
    return rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])


def signer(tx):
    keys = tx["transaction"]["message"]["accountKeys"]
    k = keys[0]
    return k.get("pubkey") if isinstance(k, dict) else k


# ---------- 1) operaciones de decu ----------
def decu_positions(hours: float):
    now, cursor, rows = time.time(), None, []
    for _ in range(60):
        d = st_get(f"/wallet/{W}/trades", **({"cursor": cursor} if cursor else {}))
        if not d:
            break
        t = d.get("trades", [])
        rows += t
        cursor = d.get("nextCursor")
        if not t or not cursor or now - t[-1].get("time", 0) / 1000 > hours * 3600:
            break
    pos = {}
    for t in rows:
        ts = t.get("time", 0) / 1000
        if now - ts > hours * 3600:
            continue
        fr, to = t.get("from") or {}, t.get("to") or {}
        if fr.get("address") == SOL and to.get("address") not in (None, SOL):
            m, side, sol, tok = to["address"], "buy", float(fr.get("amount") or 0), to
        elif to.get("address") == SOL and fr.get("address") not in (None, SOL):
            m, side, sol, tok = fr["address"], "sell", float(to.get("amount") or 0), fr
        else:
            continue
        p = pos.setdefault(m, {"mint": m, "symbol": (tok.get("token") or {}).get("symbol"), "buys": [], "sells": []})
        p[side + "s"].append({"ts": ts, "sol": sol, "tx": t.get("tx"), "mcap_usd": tok.get("marketCap")})
    for p in pos.values():
        p["buys"].sort(key=lambda x: x["ts"]); p["sells"].sort(key=lambda x: x["ts"])
        p["sol_in"] = round(sum(b["sol"] for b in p["buys"]), 4)
        p["sol_out"] = round(sum(s["sol"] for s in p["sells"]), 4)
        p["ret"] = round(p["sol_out"] / p["sol_in"] - 1, 3) if p["sol_in"] and p["sells"] else None
        p["first_buy"] = p["buys"][0] if p["buys"] else None
        p["hold_s"] = round(p["sells"][-1]["ts"] - p["buys"][0]["ts"]) if p["buys"] and p["sells"] else None
    print(f"trades de decu bajados: {len(rows)} | tokens en {hours:.0f} h: {len(pos)}")
    return pos


# ---------- 2) qué se veía antes de su compra ----------
def funder_of(wallet: str):
    """Primera billetera que le mandó SOL (fondeo) y cuántas firmas tiene la billetera (vieja/nueva)."""
    sigs, before = [], None
    for _ in range(3):                                # hasta 3000 firmas hacia atrás
        page = rpc("getSignaturesForAddress", [wallet, {"limit": 1000, **({"before": before} if before else {})}]) or []
        sigs += page
        if len(page) < 1000:
            break
        before = page[-1]["signature"]
    if not sigs:
        return None, 0, None
    oldest = [s for s in sigs[-6:] if not s.get("err")][::-1]
    for s in oldest:
        tx = get_tx(s["signature"])
        if not tx:
            continue
        for ins in tx["transaction"]["message"].get("instructions", []) + [i for x in (tx.get("meta") or {}).get("innerInstructions", []) for i in x.get("instructions", [])]:
            pr = ins.get("parsed") if isinstance(ins, dict) else None
            if isinstance(pr, dict) and pr.get("type") in ("transfer", "transferWithSeed", "createAccount") and (pr.get("info") or {}).get("destination", (pr.get("info") or {}).get("newAccount")) == wallet:
                info = pr["info"]
                return info.get("source"), len(sigs), sigs[-1].get("blockTime")
    return None, len(sigs), sigs[-1].get("blockTime")


def token_context(p: dict) -> dict:
    fb = p["first_buy"]
    m = p["mint"]
    out = {"mint": m, "symbol": p["symbol"], "decu_first_sol": round(fb["sol"], 3), "decu_sol_in": p["sol_in"], "decu_ret": p["ret"],
           "decu_hold_s": p["hold_s"], "decu_mcap_usd": round(fb["mcap_usd"] or 0), "n_decu_buys": len(p["buys"])}
    sigs = rpc("getSignaturesForAddress", [m, {"limit": 1000, "before": fb["tx"]}]) or []
    my = rpc("getSignatureStatuses", [[fb["tx"]], {"searchTransactionHistory": True}]) or {}
    my_slot = ((my.get("value") or [None])[0] or {}).get("slot")
    ok = [s for s in sigs if not s.get("err")]
    out["n_tx_before"] = len(ok); out["n_failed_before"] = len(sigs) - len(ok); out["history_truncated"] = len(sigs) >= 1000
    if not ok:
        return out
    create = ok[-1]
    out["secs_from_create"] = (fb["ts"] - create["blockTime"]) if create.get("blockTime") else None
    out["slots_from_create"] = (my_slot - create["slot"]) if my_slot else None
    ctx = get_tx(create["signature"])
    creator = signer(ctx) if ctx else None
    out["creator"] = creator
    logs = (ctx.get("meta") or {}).get("logMessages") or [] if ctx else []
    out["create_program"] = "pump" if any(PUMP in l for l in logs) else "otro"
    dev_tr = [t for t in decode_trades_from_logs(logs) if t["mint"] == m and t["is_buy"]]
    out["dev_buy_sol"] = round(sum(t["sol"] for t in dev_tr), 3)
    # compras antes de decu: hasta 40 tx (las 20 primeras y las 20 últimas antes de él)
    pre = ok[:-1][::-1]                               # cronológico, sin la creación
    pick = pre if len(pre) <= 40 else pre[:20] + pre[-20:]
    buyers, sells_by, last = defaultdict(float), defaultdict(float), None
    for s in pick:
        tx = get_tx(s["signature"])
        if not tx:
            continue
        who = signer(tx)
        for t in decode_trades_from_logs((tx.get("meta") or {}).get("logMessages") or []):
            if t["mint"] != m:
                continue
            if t["is_buy"]:
                buyers[who] += t["sol"]
            else:
                sells_by[who] += t["sol"]
            last = {"wallet": who, "sol": round(t["sol"], 3), "buy": t["is_buy"], "secs_before": round(fb["ts"] - (s.get("blockTime") or fb["ts"]), 1)}
    out["pre_buyers"] = {w: round(v, 3) for w, v in sorted(buyers.items(), key=lambda kv: -kv[1])}
    out["pre_sellers"] = {w: round(v, 3) for w, v in sells_by.items()}
    out["n_pre_buyers"] = len(buyers); out["pre_buy_sol"] = round(sum(buyers.values()), 3)
    out["dev_sold_before"] = round(sells_by.get(creator, 0), 3) if creator else None
    out["last_trade_before"] = last
    out["creator_also_buyer_count"] = None
    # metadatos
    ti = st_get(f"/tokens/{m}") or {}
    tk = ti.get("token") or {}
    ext = tk.get("strictSocials") or {}
    tw = tk.get("twitter") or ext.get("twitter") or ""
    img = tk.get("image") or ""
    if "url=" in img:
        img = img.split("url=", 1)[1]
    out.update({"name": tk.get("name"), "description": (tk.get("description") or "")[:160], "twitter": tw,
                "website": tk.get("website") or ext.get("website") or "", "telegram": tk.get("telegram") or ext.get("telegram") or "",
                "image_host": urlparse(img).netloc if img else "", "created_on": tk.get("createdOn") or ""})
    return out


def creator_info(creator: str) -> dict:
    f, n, first_ts = funder_of(creator)
    return {"funder": f, "n_sigs": n, "first_seen": first_ts}


def x_handle(url: str) -> str:
    if not url:
        return ""
    try:
        u = urlparse(url if "://" in url else "https://" + url)
        if u.netloc.replace("www.", "") in ("x.com", "twitter.com"):
            parts = [x for x in u.path.split("/") if x]
            if not parts:
                return "x:(vacío)"
            if parts[0] in ("i", "search", "hashtag"):
                return f"x:{parts[0]}/{'/'.join(parts[1:2])}"
            return ("x:@" + parts[0].lower()) + ("/status" if len(parts) > 1 and parts[1] == "status" else "")
        return u.netloc
    except Exception:  # noqa: BLE001
        return "?"


def pct(v, q):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(len(v) * q))], 2) if v else None


def main():
    n_tok = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    hours = float(sys.argv[2]) if len(sys.argv) > 2 else 48
    t0 = time.time()
    pos = decu_positions(hours)
    big = sorted([p for p in pos.values() if p["first_buy"] and max(b["sol"] for b in p["buys"]) >= MIN_SOL],
                 key=lambda p: -p["first_buy"]["ts"])
    small = [p for p in pos.values() if p["first_buy"] and max(b["sol"] for b in p["buys"]) < MIN_SOL]
    print(f"tokens con compra >= {MIN_SOL} SOL: {len(big)} | solo compras chicas: {len(small)}")
    rets_big = [p["ret"] for p in big if p["ret"] is not None]; rets_small = [p["ret"] for p in small if p["ret"] is not None]
    print(f"resultado de decu: grandes acierto {sum(r > 0 for r in rets_big)}/{len(rets_big)} mediana {pct(rets_big, .5)} | chicas acierto {sum(r > 0 for r in rets_small)}/{len(rets_small)} mediana {pct(rets_small, .5)}")
    # ¿la primera compra es la grande o empieza con una chica (sondeo)?
    first_big = sum(1 for p in big if p["buys"][0]["sol"] >= MIN_SOL)
    print(f"en los grandes, la PRIMERA compra ya es >= {MIN_SOL} SOL en {first_big}/{len(big)}")
    sel = big[:n_tok]
    with ThreadPoolExecutor(6) as ex:
        rows = list(ex.map(lambda p: _safe(token_context, p), sel))
    rows = [r for r in rows if r]
    creators = sorted({r["creator"] for r in rows if r.get("creator")})
    with ThreadPoolExecutor(6) as ex:
        cinfo = dict(zip(creators, ex.map(lambda c: _safe(creator_info, c) or {}, creators)))
    for r in rows:
        r["creator_info"] = cinfo.get(r.get("creator"), {})
    json.dump({"ts": time.time(), "hours": hours, "rows": rows, "positions": list(pos.values())}, open("state/decu_triggers.json", "w"))
    print(f"\ncontexto reconstruido de {len(rows)} tokens en {time.time() - t0:.0f} s\n")

    # ---------- resumen ----------
    def dist(k):
        return f"p25 {pct([r.get(k) for r in rows], .25)} | mediana {pct([r.get(k) for r in rows], .5)} | p75 {pct([r.get(k) for r in rows], .75)}"
    for k in ("secs_from_create", "slots_from_create", "n_tx_before", "n_pre_buyers", "pre_buy_sol", "dev_buy_sol", "decu_mcap_usd", "decu_first_sol", "decu_hold_s", "decu_ret"):
        print(f"{k:20s} {dist(k)}")
    print("programa de creación:", Counter(r.get("create_program") for r in rows).most_common())
    print("lanzadas desde (createdOn):", Counter(r.get("created_on") for r in rows).most_common(8))
    print("host de la imagen:", Counter(r.get("image_host") for r in rows).most_common(8))
    print("tiene X:", sum(bool(r.get("twitter")) for r in rows), "| web:", sum(bool(r.get("website")) for r in rows), "| telegram:", sum(bool(r.get("telegram")) for r in rows), "de", len(rows))
    print("links de X:", Counter(x_handle(r.get("twitter")) for r in rows if r.get("twitter")).most_common(15))
    print("dev vendió antes de que compre decu:", sum(1 for r in rows if (r.get("dev_sold_before") or 0) > 0), "de", len(rows))
    cr = Counter(r.get("creator") for r in rows if r.get("creator"))
    print("creadores repetidos:", [(c[:8], n) for c, n in cr.most_common(8) if n > 1])
    fu = Counter((r.get("creator_info") or {}).get("funder") for r in rows if (r.get("creator_info") or {}).get("funder"))
    print("fondeadores de creadores repetidos:", [(c[:8], n) for c, n in fu.most_common(8) if n > 1])
    print("¿decu fondeó a algún creador?:", sum(1 for r in rows if (r.get("creator_info") or {}).get("funder") == W))
    nsig = [(r.get("creator_info") or {}).get("n_sigs") for r in rows]
    print("firmas del creador (billetera nueva si es chica):", f"p25 {pct(nsig, .25)} mediana {pct(nsig, .5)} p75 {pct(nsig, .75)}")
    pb = Counter(w for r in rows for w in (r.get("pre_buyers") or {}) if w != r.get("creator") and w != W)
    rep = [(w, n) for w, n in pb.most_common(25) if n >= 3]
    print(f"billeteras que compran ANTES que decu en >= 3 tokens: {len(rep)}")
    for w, n in rep[:20]:
        toks = [r for r in rows if w in (r.get("pre_buyers") or {})]
        rr = [r["decu_ret"] for r in toks if r.get("decu_ret") is not None]
        print(f"   {w} en {n}/{len(rows)} tokens | SOL med {pct([r['pre_buyers'][w] for r in toks], .5)} | ret decu en esos: mediana {pct(rr, .5)}")
    lt = Counter((r.get("last_trade_before") or {}).get("wallet") for r in rows if r.get("last_trade_before"))
    print("última billetera antes de decu (repetidas):", [(w[:8], n) for w, n in lt.most_common(8) if n > 1])
    print("segundos entre el último trade y decu:", pct([(r.get("last_trade_before") or {}).get("secs_before") for r in rows], .5))
    # ganadores vs perdedores de decu: ¿qué los separa?
    win = [r for r in rows if (r.get("decu_ret") or 0) > 0]; lose = [r for r in rows if r.get("decu_ret") is not None and r["decu_ret"] <= 0]
    for k in ("secs_from_create", "n_pre_buyers", "pre_buy_sol", "dev_buy_sol", "decu_mcap_usd", "decu_first_sol"):
        print(f"  {k:18s} ganó: {pct([r.get(k) for r in win], .5)}  perdió: {pct([r.get(k) for r in lose], .5)}")
    print(f"  tiene X           ganó: {sum(bool(r.get('twitter')) for r in win)}/{len(win)}  perdió: {sum(bool(r.get('twitter')) for r in lose)}/{len(lose)}")
    print("\nmuestra (10 más recientes):")
    for r in rows[:10]:
        print(json.dumps({k: r.get(k) for k in ("symbol", "name", "secs_from_create", "n_pre_buyers", "pre_buy_sol", "dev_buy_sol", "decu_mcap_usd",
                                                "decu_first_sol", "decu_ret", "decu_hold_s", "twitter", "image_host", "created_on", "description")}, ensure_ascii=False)[:420])


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception as e:  # noqa: BLE001
        print("  error", fn.__name__, str(e)[:150])
        return None


if __name__ == "__main__":
    main()
