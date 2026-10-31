"""Censo de vida de memecoins de pump.fun (31/10/2026).

Objetivo: dejar de probar reglas sueltas y medir primero cómo viven y mueren los lanzamientos,
para diseñar canastas y entradas por escalón sobre datos. Muestra sin sesgo de supervivencia
(búsqueda por fecha de creación incluye muertos), estratificada por hora.

Estratos:
  A  todos los lanzamientos        (sin filtro)       K_A por hora, 7 días, velas 1m 6 h
  B  arrancaron (>= 40 compras)                       K_B por hora, 7 días, velas 1m 6 h
  C  grandes (>= 1000 compras)                        K_C por hora, 14 días, velas 1m 6 h + 5m 48 h
Además, por hora: total de lanzamientos con y sin filtro (para pesar los estratos).

Salida cruda en data/censo/ (no se publica). `pack` arma state/research/censo/<estrato>.json.gz con
mcap (USD, entero) por minuto: h, l, c y volumen (USD), alineado a la creación.

Uso (en el servidor):
  python3 -m fomo_intel.experiments.censo probe
  python3 -m fomo_intel.experiments.censo pull --ka 8 --kb 20 --kc 10 --threads 3
  python3 -m fomo_intel.experiments.censo pack
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

BASE = "https://data.solanatracker.io"
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
RAW = Path("data/censo")
OUT = Path("state/research/censo")
LOG = OUT / "pull.log"
SUPPLY = 1_000_000_000
_lock = threading.Lock()
_nreq = 0


def log(*a):
    OUT.mkdir(parents=True, exist_ok=True)
    s = time.strftime("%Y-%m-%d %H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(s, flush=True)
    with _lock:
        with open(LOG, "a") as f:
            f.write(s + "\n")


def get(path, **params):
    global _nreq
    for i in range(5):
        try:
            r = requests.get(f"{BASE}{path}", headers=H, params=params, timeout=40)
        except requests.RequestException:
            time.sleep(2 + i * 2); continue
        with _lock:
            _nreq += 1
        if r.status_code == 429:
            time.sleep(4 + i * 4); continue
        if r.status_code == 404:
            return None
        if r.status_code >= 500:
            time.sleep(2 + i * 2); continue
        if r.status_code >= 400:
            log("HTTP", r.status_code, path, str(params)[:120], r.text[:200]); return None
        try:
            return r.json()
        except ValueError:
            return None
    return None


def candles(mint, t0, t1, itype):
    d = get(f"/chart/{mint}", type=itype, time_from=int(t0), time_to=int(t1))
    raw = (d or {}).get("oclhv") if isinstance(d, dict) else d
    cs = []
    for c in raw or []:
        t = int(c.get("time") or 0); t = t // 1000 if t > 1e11 else t
        cs.append([t, float(c.get("open") or 0), float(c.get("high") or 0), float(c.get("low") or 0),
                   float(c.get("close") or 0), float(c.get("volume") or 0)])
    cs.sort(key=lambda x: x[0])
    return cs


def created_of(t):
    c = t.get("createdAt") or (t.get("tokenDetails") or {}).get("time") or 0
    return int(c / 1000) if c > 1e11 else int(c)


def meta_of(t, stratum):
    return {"mint": t.get("mint"), "s": stratum, "sym": t.get("symbol"), "name": t.get("name"), "created": created_of(t),
            "dev": t.get("deployer") or (t.get("tokenDetails") or {}).get("creator"), "status": t.get("status"),
            "market": t.get("market"), "socials": t.get("socials"), "holders_now": t.get("holders"), "buys": t.get("buys"),
            "sells": t.get("sells"), "mcap_now": t.get("marketCapUsd"), "top10_now": t.get("top10"), "dev_now": t.get("dev"),
            "snipers_now": t.get("snipers"), "insiders_now": t.get("insiders"), "bundlers_now": t.get("bundlers")}


# ---------------------------------------------------------------- probe
def probe():
    d = get("/credits")
    print("credits:", json.dumps(d)[:400])
    now = time.time()
    hi, lo = int((now - 8 * 3600) * 1000), int((now - 9 * 3600) * 1000)
    for extra in ({}, {"minBuys": 40}, {"minBuys": 1000}):
        r = get("/search", launchpad="pumpfun", minCreatedAt=lo, maxCreatedAt=hi, sortBy="createdAt", sortOrder="desc", limit=3, **extra)
        print("search 1h", extra, "total=", (r or {}).get("total"), "hasMore=", (r or {}).get("hasMore"), "n=", len((r or {}).get("data") or []))
        if r and r.get("data") and not extra:
            print("campos:", sorted(r["data"][0].keys()))
            print("ejemplo:", json.dumps(r["data"][0])[:1500])
        if r and r.get("data") and extra.get("minBuys") == 1000:
            t = r["data"][0]; c0 = created_of(t)
            m1 = candles(t["mint"], c0 - 60, c0 + 24 * 3600, "1m")
            m5 = candles(t["mint"], c0 - 60, c0 + 48 * 3600, "5m")
            print("velas 1m 24h:", len(m1), "primera", m1[:1], "última t-c0(min)", (m1[-1][0] - c0) / 60 if m1 else None)
            print("velas 5m 48h:", len(m5), "última t-c0(h)", (m5[-1][0] - c0) / 3600 if m5 else None)
            print("mcap pico aprox:", max(c[2] for c in m1) * SUPPLY if m1 else None, "mcap_now", t.get("marketCapUsd"))
    print("requests usados en probe:", _nreq)


# ---------------------------------------------------------------- pull
def hour_windows(days, end_lag_h):
    now = time.time()
    end = int((now - end_lag_h * 3600) // 3600 * 3600)
    return [(end - (i + 1) * 3600, end - i * 3600) for i in range(int(days * 24))]


def pull(ka, kb, kc, threads):
    RAW.mkdir(parents=True, exist_ok=True); (RAW / "charts").mkdir(exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    plan = [("A", ka, 7, {}, 7, 6.0, False), ("B", kb, 7, {"minBuys": 40}, 7, 6.0, False), ("C", kc, 14, {"minBuys": 1000}, 50, 6.0, True)]
    totals_p = RAW / "totals.jsonl"; meta_p = RAW / "meta.jsonl"
    done_tot = set()
    if totals_p.exists():
        for l in open(totals_p): done_tot.add((json.loads(l)["s"], json.loads(l)["h0"]))
    seen = set()
    if meta_p.exists():
        for l in open(meta_p): seen.add(json.loads(l)["mint"])
    # 1) listas por hora
    todo = []
    for s, k, days, extra, lag, _, _ in plan:
        for h0, h1 in hour_windows(days, lag):
            if (s, h0) in done_tot:
                continue
            r = get("/search", launchpad="pumpfun", minCreatedAt=h0 * 1000, maxCreatedAt=h1 * 1000, sortBy="createdAt", sortOrder="desc", limit=max(k, 1), **extra)
            data = (r or {}).get("data") or []
            with open(totals_p, "a") as f:
                f.write(json.dumps({"s": s, "h0": h0, "total": (r or {}).get("total"), "n": len(data)}) + "\n")
            with open(meta_p, "a") as f:
                for t in data[:k]:
                    if t.get("mint") and t["mint"] not in seen:
                        seen.add(t["mint"]); f.write(json.dumps(meta_of(t, s)) + "\n")
        log("listas", s, "ok; requests", _nreq)
    # 2) velas
    metas = [json.loads(l) for l in open(meta_p)]
    random.seed(7); random.shuffle(metas)
    cfg = {p[0]: p for p in plan}

    def job(m):
        f = RAW / "charts" / f"{m['mint']}.json.gz"
        if f.exists():
            return
        c0 = m["created"]; s = m["s"]
        out = {"m1": candles(m["mint"], c0 - 60, c0 + int(cfg[s][5] * 3600) + 60, "1m")}
        if cfg[s][6]:
            out["m5"] = candles(m["mint"], c0 - 60, c0 + 48 * 3600, "5m")
        with gzip.open(f, "wt") as g:
            json.dump(out, g)

    t0 = time.time(); n = 0
    with ThreadPoolExecutor(threads) as ex:
        for _ in ex.map(job, metas):
            n += 1
            if n % 200 == 0:
                log(f"velas {n}/{len(metas)} requests {_nreq} ({(time.time()-t0)/60:.0f} min)")
    log("pull terminado", n, "requests", _nreq)
    pack()


# ---------------------------------------------------------------- pack
def grid(cs, c0, step, nbins):
    """mcap por bin (h, l, c) y volumen; bins sin trades heredan el cierre anterior (h=l=c=prev, v=0)."""
    H_, L_, C_, V_ = [0] * nbins, [0] * nbins, [0] * nbins, [0] * nbins
    by = {}
    for t, o, h, l, c, v in cs:
        b = (t - c0) // step
        if b < 0:
            b = 0
        if b >= nbins:
            continue
        if b in by:
            x = by[b]; x[0] = max(x[0], h); x[1] = min(x[1], l); x[2] = c; x[3] += v
        else:
            by[b] = [h, l, c, v]
    prev = 0
    last_trade = -1
    for b in range(nbins):
        if b in by:
            h, l, c, v = by[b]
            H_[b], L_[b], C_[b], V_[b] = int(h * SUPPLY), int(l * SUPPLY), int(c * SUPPLY), int(v)
            prev = C_[b]; last_trade = b
        else:
            H_[b] = L_[b] = C_[b] = prev
    return {"h": H_, "l": L_, "c": C_, "v": V_, "last": last_trade}


def pack():
    meta_p = RAW / "meta.jsonl"
    metas = {json.loads(l)["mint"]: json.loads(l) for l in open(meta_p)}
    by = {"A": [], "B": [], "C": []}
    for mint, m in metas.items():
        f = RAW / "charts" / f"{mint}.json.gz"
        if not f.exists():
            continue
        d = json.load(gzip.open(f, "rt"))
        row = dict(m)
        row["g1"] = grid(d.get("m1") or [], m["created"], 60, 360)
        if "m5" in d:
            row["g5"] = grid(d.get("m5") or [], m["created"], 300, 576)
        by[m["s"]].append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    for s, rows in by.items():
        with gzip.open(OUT / f"{s}.json.gz", "wt") as g:
            json.dump(rows, g)
        log("pack", s, len(rows))
    tot = [json.loads(l) for l in open(RAW / "totals.jsonl")]
    json.dump(tot, open(OUT / "totals.json", "w"))
    log("pack ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--ka", type=int, default=8)
    ap.add_argument("--kb", type=int, default=20)
    ap.add_argument("--kc", type=int, default=10)
    ap.add_argument("--threads", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "probe":
        probe()
    elif a.cmd == "pull":
        pull(a.ka, a.kb, a.kc, a.threads)
    elif a.cmd == "pack":
        pack()
    else:
        sys.exit("cmd: probe | pull | pack")
