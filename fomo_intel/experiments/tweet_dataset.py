"""Dataset completo de tokens de tweet de la sombra: texto del tweet (syndication), flujo del 1er/2do segundo y resultado simulado
entrando al seg 2 (velas 1 s de Solana Tracker), + si decu lo compró. Salida: state/tweet_dataset.json (se va completando)."""
import json, os, sys, time, threading, requests
from concurrent.futures import ThreadPoolExecutor
ST = "https://data.solanatracker.io"; H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
OUT = "state/tweet_dataset.json"
rows = [json.loads(l) for l in open("state/tweetshadow/creates_helius.jsonl")]
rows.sort(key=lambda r: r["seen_ts"])
t0 = rows[0]["seen_ts"]
sig = [json.loads(l) for l in open("state/signals.jsonl") if l.strip()]
decu = {}
for s in sig:
    if s["ts"] >= t0 and (s.get("sol") or 0) >= 1: decu.setdefault(s["mint"], s["ts"])
cnt = {}
tw = []
for r in rows:
    if not r["is_tweet"]: continue
    k = r["twitter"].split("/status/")[1].split("?")[0].split("/")[0]
    cnt[k] = cnt.get(k, 0) + 1
    r["tid"], r["rank"] = k, cnt[k]
    tw.append(r)
now = time.time()
tw = [r for r in tw if now - r["seen_ts"] > 300]          # resultado a 80 s ya disponible
lim = int(sys.argv[1]) if len(sys.argv) > 1 else 0
done = {}
if os.path.exists(OUT):
    for x in json.load(open(OUT)): done[x["mint"]] = x
todo = [r for r in tw if r["mint"] not in done]
if lim: todo = todo[-lim:]
print(f"tokens de tweet: {len(tw)} | ya hechos {len(done)} | a procesar {len(todo)}", flush=True)
tcache, lock = {}, threading.Lock()

def tweet(tid):
    if tid in tcache: return tcache[tid]
    out = {}
    for i in range(2):
        try:
            r = requests.get(f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=a", timeout=6)
            if r.status_code == 200:
                j = r.json(); q = j.get("quoted_tweet") or {}
                out = {"text": (j.get("text") or "")[:400], "likes": j.get("favorite_count"), "author_name": (j.get("user") or {}).get("name"),
                       "verified": bool((j.get("user") or {}).get("is_blue_verified")), "media": bool(j.get("mediaDetails") or j.get("photos")),
                       "quote_text": (q.get("text") or "")[:200], "quote_author": (q.get("user") or {}).get("screen_name")}
                break
            if r.status_code == 429: time.sleep(3)
        except Exception: time.sleep(1)
    tcache[tid] = out
    return out

def candles(m, c0):
    for i in range(3):
        try:
            r = requests.get(f"{ST}/chart/{m}", headers=H, params={"type": "1s", "time_from": int(c0) - 3, "time_to": int(c0) + 200}, timeout=30)
            if r.ok: return r.json().get("oclhv", [])
            if r.status_code == 429: time.sleep(2 * (i + 1))
        except Exception: time.sleep(1)
    return []

def sim(cs, c0, es, exit_s=80, slip=0.08, stop=0.35, tp=1.0):
    pre = [c for c in cs if c["time"] <= c0 + es]
    if not pre: return None
    px = float(pre[-1]["close"]) * (1 + slip)
    for c in cs:
        if c["time"] <= c0 + es: continue
        if float(c["low"]) <= px * (1 - stop): return -stop - 0.02
        if float(c["high"]) >= px * (1 + tp): return tp - 0.02
        if c["time"] >= c0 + exit_s: return float(c["close"]) / px * 0.98 - 1
    return float(cs[-1]["close"]) / px * 0.98 - 1 if cs else None

def work(r):
    c0 = int(r["seen_ts"]); cs = candles(r["mint"], r["seen_ts"])
    o = float(cs[0]["open"]) if cs else 0
    f = {"mint": r["mint"], "symbol": r["symbol"], "name": r["name"], "ts": r["seen_ts"], "tid": r["tid"], "rank": r["rank"],
         "author": r.get("tweet_author"), "tw2c": r.get("tweet_to_create_s"), "tool": r["meta_src"], "website": bool(r["website"]),
         "vanity": not r["mint"].endswith("pump"), "decu": r["mint"] in decu, "decu_lat": round(decu[r["mint"]] - r["seen_ts"], 1) if r["mint"] in decu else None,
         "n_candles": len(cs)}
    for s in (1, 2):
        sub = [c for c in cs if c["time"] <= c0 + s]
        f[f"vol_s{s}"] = round(sum(float(c.get("volume") or 0) for c in sub), 1)
        f[f"px_s{s}"] = round(float(sub[-1]["close"]) / o, 3) if sub and o else None
    f["max_200"] = round(max(float(c["high"]) for c in cs) / o, 2) if cs and o else None
    f["ret_s2"] = sim(cs, c0, 2); f["ret_s1"] = sim(cs, c0, 1)
    f.update({"tw_" + k: v for k, v in tweet(r["tid"]).items()})
    return f

res = list(done.values()); t1 = time.time()
with ThreadPoolExecutor(8) as ex:
    for i, f in enumerate(ex.map(work, todo)):
        res.append(f)
        if i % 500 == 499:
            json.dump(res, open(OUT, "w")); print(f"{i+1}/{len(todo)} en {time.time()-t1:.0f}s", flush=True)
json.dump(res, open(OUT, "w"))
v = [x["ret_s2"] for x in res if x.get("ret_s2") is not None]
print(f"listo: {len(res)} filas | con texto {sum(1 for x in res if x.get('tw_text'))} | decu {sum(x['decu'] for x in res)} | ret_s2 medio todos {sum(v)/len(v):+.3f}", flush=True)
