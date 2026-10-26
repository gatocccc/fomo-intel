"""Experimentos 26/10: "tokens con red detrás" (creador con historia + socials), venta escalonada.

Dos universos, misma maquinaria:
  bags  -> launchpad Bags (creador verificado, fee perpetua), entrada tardía (60 min), tenencia hasta 24 h
  pump  -> pump.fun con >= min_buys compras, entrada al minuto 3, tenencia 6 h

Protocolo: precio ejecutable (cierre de la vela de entrada + slippage + fee), stop al cierre, muestra sin
sesgo de supervivencia (search por fecha de creación incluye tokens muertos), mitad vieja = diseño /
mitad nueva = prueba, y control = "todos los tokens del universo con la misma salida".

Uso:
  python3 -m fomo_intel.experiments.red discover
  python3 -m fomo_intel.experiments.red pull bags --days 30 --max 2500
  python3 -m fomo_intel.experiments.red pull pump --hours 36 --max 2000 --min-buys 40
  python3 -m fomo_intel.experiments.red analyze bags|pump
"""
from __future__ import annotations

import json
import os
import random
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

from fomo_intel.backtest.entrysim import SimParams, simulate

BASE = "https://data.solanatracker.io"
DIR = Path("data/exp_red")
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
SLEEP = 0.25


def get(path, **params):
    for i in range(4):
        try:
            r = requests.get(f"{BASE}{path}", headers=H, params=params, timeout=40)
        except requests.RequestException as e:
            time.sleep(2 + i * 2); continue
        time.sleep(SLEEP)
        if r.status_code == 429:
            time.sleep(5 + i * 5); continue
        if r.status_code == 404:
            return None
        if r.status_code >= 500:
            time.sleep(2 + i * 2); continue
        r.raise_for_status()
        return r.json()
    return None


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- descubrimiento
def discover():
    for lp in ("bags", "believe", "launchcoin", "bonk", "letsbonk", "boop", "moonshot", "pumpfun", "raydium-launchpad", "jupiter-studio", "zora", "heaven"):
        d = get("/search", launchpad=lp, limit=5, sortBy="createdAt", sortOrder="desc")
        n = (d or {}).get("total"); ex = ((d or {}).get("data") or [{}])[0]
        print(f"launchpad={lp:<18} total={n}  ej: {ex.get('symbol')} {ex.get('mint','')[:8]} market={ex.get('market')} createdAt={ex.get('createdAt')}")
    d = get("/search", launchpad="bags", limit=3, sortBy="createdAt", sortOrder="desc")
    if d and d.get("data"):
        print("campos de un resultado bags:", json.dumps(d["data"][0], indent=0)[:1500])


# ---------------------------------------------------------------- descarga
def search_window(launchpad, min_ms, max_ms, cap, extra):
    out, cursor, page = [], None, 1
    while len(out) < cap:
        params = dict(launchpad=launchpad, minCreatedAt=min_ms, maxCreatedAt=max_ms, sortBy="createdAt", sortOrder="desc", limit=100, **extra)
        if cursor: params["cursor"] = cursor
        else: params["page"] = page
        d = get("/search", **params)
        if not d or not d.get("data"): break
        out.extend(d["data"])
        if not d.get("hasMore"): break
        cursor = d.get("nextCursor"); page += 1
        if page % 10 == 0: log("search", launchpad, len(out), "total", d.get("total"))
    return out[:cap]


def deployer_history(dev, before_ts):
    """Historia previa del creador (tokens creados antes de `before_ts`) vía /deployer/{wallet}."""
    d = get(f"/deployer/{dev}", limit=500)
    toks = (d or {}).get("data") or (d or {}).get("tokens") or (d if isinstance(d, list) else [])
    prior = []
    for t in toks:
        tk = t.get("token") or t; pools = t.get("pools") or []
        c = tk.get("createdAt") or (tk.get("creation") or {}).get("created_time") or t.get("createdAt") or 0
        c = c / 1000 if c > 1e11 else c
        if not c or c >= before_ts - 5: continue
        curve = min(pools, key=lambda x: x.get("createdAt") or 9e18) if pools else {}
        mcap = max(((p.get("marketCap") or {}).get("usd") or 0) for p in pools) if pools else (t.get("marketCapUsd") or 0)
        graduated = len(pools) > 1 or (curve.get("curvePercentage") or 0) >= 100 or t.get("status") in ("graduated", "migrated")
        prior.append({"created": c, "graduated": bool(graduated), "mcap": mcap})
    return {"n_total_api": (d or {}).get("total") if isinstance(d, dict) else None, "prior": prior}


def chart(mint, created_ts, hours, itype="1m"):
    d = get(f"/chart/{mint}", type=itype, time_from=max(0, created_ts - 60), time_to=created_ts + int(hours * 3600))
    raw = (d or {}).get("oclhv") if isinstance(d, dict) else d
    cs = []
    for c in raw or []:
        t = int(c.get("time") or 0); t = t // 1000 if t > 1e11 else t
        cs.append({"t": t, "o": float(c.get("open") or 0), "h": float(c.get("high") or 0), "l": float(c.get("low") or 0), "c": float(c.get("close") or 0), "v": float(c.get("volume") or 0)})
    cs.sort(key=lambda x: x["t"]); return cs


def pull(universe, days=None, hours=None, cap=2000, min_buys=0, hold_h=None):
    DIR.mkdir(parents=True, exist_ok=True); (DIR / "charts").mkdir(exist_ok=True)
    now = time.time()
    span = (days or 0) * 86400 + (hours or 0) * 3600
    hold_h = hold_h or (24 if universe == "bags" else 6)
    max_ms = int((now - hold_h * 3600 - 3600) * 1000)   # solo tokens con ventana de resultado completa
    min_ms = int((now - span) * 1000)
    extra = {"minBuys": min_buys} if min_buys else {}
    lp = {"bags": "bags", "pump": "pumpfun"}[universe]
    toks = search_window(lp, min_ms, max_ms, cap, extra)
    log(universe, "tokens en ventana:", len(toks))
    outp = DIR / f"{universe}_tokens.jsonl"
    done = set()
    if outp.exists():
        for line in open(outp): done.add(json.loads(line)["mint"])
    f = open(outp, "a")
    for i, t in enumerate(toks):
        mint = t.get("mint")
        if not mint or mint in done: continue
        created = t.get("createdAt") or (t.get("tokenDetails") or {}).get("time") or 0
        created = int(created / 1000) if created > 1e11 else int(created)
        dev = t.get("deployer") or (t.get("tokenDetails") or {}).get("creator") or ""
        row = {"mint": mint, "symbol": t.get("symbol"), "name": t.get("name"), "created": created, "deployer": dev,
               "market": t.get("market"), "status": t.get("status"), "socials": t.get("socials"), "has_community": t.get("hasCoinCommunity"),
               "community_msgs": t.get("communityMessages"), "fees": t.get("fees"), "dev_pct": t.get("dev"), "top10": t.get("top10"),
               "holders": t.get("holders"), "buys": t.get("buys"), "sells": t.get("sells"), "mcap_now": t.get("marketCapUsd"), "liq_now": t.get("liquidityUsd"),
               "jupiter": t.get("jupiter"), "verified": t.get("verified"), "lp_burn": t.get("lpBurn")}
        row["dev_hist"] = deployer_history(dev, created) if dev else None
        cs = chart(mint, created, hold_h + 1.5, "1m")
        if universe == "bags":
            cs7 = chart(mint, created, 24 * 7, "1h")
            json.dump({"m1": cs, "h1": cs7}, open(DIR / "charts" / f"{mint}.json", "w"))
        else:
            json.dump({"m1": cs}, open(DIR / "charts" / f"{mint}.json", "w"))
        row["n_candles"] = len(cs)
        f.write(json.dumps(row) + "\n"); f.flush()
        if i % 50 == 0: log(universe, i, "/", len(toks), row["symbol"], "velas", len(cs), "prev. creador", len((row["dev_hist"] or {}).get("prior", [])))
    log(universe, "descarga terminada")


# ---------------------------------------------------------------- análisis
def soc_key(row):
    s = row.get("socials") or {}
    if isinstance(s, list): s = {x: True for x in s}
    tw = bool(s.get("twitter")); tg = bool(s.get("telegram")); web = bool(s.get("website"))
    return ("tw" if tw else "-") + ("tg" if tg else "-") + ("web" if web else "-")


def creator_key(row, universe):
    h = row.get("dev_hist") or {}; prior = h.get("prior") or []
    if not prior: return "sin historia"
    created = row["created"]
    last24 = sum(1 for p in prior if created - p["created"] < 86400)
    if last24 >= 5 or len(prior) >= 30: return "fabrica"
    if universe == "bags":
        ok = sum(1 for p in prior if (p.get("mcap") or 0) >= 100_000)
    else:
        ok = sum(1 for p in prior if p.get("graduated"))
    if ok >= 2: return "historia buena (>=2 exitos)"
    if ok == 1: return "historia buena (1 exito)"
    return "historia sin exitos"


def analyze(universe, entry_min=None, hold_min=None):
    rows = [json.loads(l) for l in open(DIR / f"{universe}_tokens.jsonl")]
    entry_min = entry_min or (60 if universe == "bags" else 3)
    hold_min = hold_min or (24 * 60 if universe == "bags" else 360)
    P = SimParams(entry_min=entry_min, max_wait_min=15 if universe == "bags" else 2, slippage=0.03 if universe == "bags" else 0.05, fee=0.01,
                  stop=0.40, trail=0.30, tp_levels=((1.5, 0.25), (2.0, 0.25), (3.0, 0.25)), max_hold_min=hold_min, fill="close", stop_fill="close", dead_haircut=0.5)
    res = []
    for r in rows:
        cp = DIR / "charts" / f"{r['mint']}.json"
        if not cp.exists(): continue
        cs = json.load(open(cp))["m1"]
        if len(cs) < 3: continue
        s = simulate(r["mint"], r["symbol"] or "", r["created"], cs, P)
        if not s.entered: continue
        res.append({**r, "ret": s.ret, "peak": s.peak_mult, "exit": s.exits[-1][3] if s.exits else "", "soc": soc_key(r), "cre": creator_key(r, universe)})
    log(universe, "tokens:", len(rows), "con entrada posible:", len(res))
    res.sort(key=lambda x: x["created"]); half = len(res) // 2
    halves = {"diseño (mitad vieja)": res[:half], "PRUEBA (mitad nueva)": res[half:]}

    def desc(name, g, n_min=15):
        if len(g) < n_min: print(f"   {name:<34} n={len(g):4d} (poca muestra)"); return
        rets = [x["ret"] for x in g]; w = sum(1 for z in rets if z > 0) / len(rets)
        big = sum(1 for z in rets if z < -0.5) / len(rets)
        print(f"   {name:<34} n={len(g):4d} acierto={w:5.0%} ret/op={sum(rets)/len(rets):+.3f} mediana={st.median(rets):+.3f} <-50%: {big:4.0%} salidas={dict(Counter(x['exit'] for x in g).most_common(3))}")

    for hname, g in halves.items():
        print(f"\n== {universe} | entrada min {entry_min} | tenencia {hold_min} min | {hname} ==")
        desc("CONTROL: todos", g)
        print("  por socials:")
        for k in sorted({x["soc"] for x in g}): desc(f"  {k}", [x for x in g if x["soc"] == k])
        print("  por historia del creador:")
        for k in ("sin historia", "historia sin exitos", "historia buena (1 exito)", "historia buena (>=2 exitos)", "fabrica"): desc(f"  {k}", [x for x in g if x["cre"] == k])
        print("  combinadas:")
        desc("  socials tw+web o mas, no fabrica", [x for x in g if x["soc"] in ("tw-web", "twtgweb") and x["cre"] != "fabrica"])
        desc("  historia buena + algun social", [x for x in g if x["cre"].startswith("historia buena") and x["soc"] != "---"])
        desc("  historia buena + tw+web", [x for x in g if x["cre"].startswith("historia buena") and x["soc"] in ("tw-web", "twtgweb")])
        if universe == "bags":
            desc("  verificado jupiter", [x for x in g if x.get("jupiter")])
            desc("  con comunidad", [x for x in g if x.get("has_community")])
        random.seed(7)
        desc("  AZAR (30% al azar)", [x for x in g if random.random() < 0.3])
    # variantes de salida sobre la mitad de diseño únicamente (para no contaminar la prueba)
    print("\n  variantes de salida (solo mitad de diseño, grupo 'historia buena + algun social'):")
    sel = {x["mint"] for x in halves["diseño (mitad vieja)"] if x["cre"].startswith("historia buena") and x["soc"] != "---"}
    for name, kw in (("escalera 1.5/2/3 + trail30 stop40", {}), ("escalera 1.3/1.6/2 trail20 stop30", dict(tp_levels=((1.3, .34), (1.6, .33), (2.0, .33)), trail=.2, stop=.3)),
                     ("50% a 2x, trail 20, stop 30", dict(tp_levels=((2.0, .5),), trail=.2, stop=.3)), ("solo trailing 25 stop 35", dict(tp_levels=(), trail=.25, stop=.35))):
        p2 = SimParams(**{**P.__dict__, **kw}); g = []
        for r in rows:
            if r["mint"] not in sel: continue
            cs = json.load(open(DIR / "charts" / f"{r['mint']}.json"))["m1"]; s = simulate(r["mint"], r["symbol"] or "", r["created"], cs, p2)
            if s.entered: g.append({"ret": s.ret, "exit": s.exits[-1][3] if s.exits else ""})
        desc(name, g)
    json.dump(res, open(DIR / f"{universe}_results.json", "w"))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "discover": discover()
    elif a[0] == "pull":
        kw = {}; i = 2
        while i < len(a):
            k = a[i].lstrip("-").replace("-", "_"); kw[k] = float(a[i + 1]); i += 2
        pull(a[1], days=kw.get("days"), hours=kw.get("hours"), cap=int(kw.get("max", 2000)), min_buys=int(kw.get("min_buys", 0)), hold_h=kw.get("hold_h"))
    elif a[0] == "analyze":
        kw = {}; i = 2
        while i < len(a):
            k = a[i].lstrip("-").replace("-", "_"); kw[k] = int(a[i + 1]); i += 2
        analyze(a[1], **kw)
