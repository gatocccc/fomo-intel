"""¿Qué se ve en los primeros 2 s del token y en el tweet que separe lo que compra decu? (antes de su compra: la más rápida fue a 3,1 s)
Features: velas 1 s (precio y volumen al seg 1-2 vs creación), tweet vía syndication pública (likes, seguidores del autor, texto)."""
import json, random, time, requests
from fomo_intel.experiments import tweet_sim as T
rows = sorted(T.rows, key=lambda r: r["seen_ts"]); first = T.first
from collections import defaultdict
cnt = defaultdict(int)
for r in rows:
    if r["is_tweet"]:
        k = T.tid(r); cnt[k] += 1; r["rank"] = cnt[k]
tw = [r for r in rows if r["is_tweet"]]
picks = [r for r in tw if r["mint"] in first]
random.seed(3)
ctrl = random.sample([r for r in tw if r["mint"] not in first and r["rank"] == 1], 120)

def early(r):
    m, c0 = r["mint"], r["seen_ts"]
    try:
        x = requests.get(f"{T.ST}/chart/{m}", headers=T.H, params={"type": "1s", "time_from": int(c0) - 3, "time_to": int(c0) + 4}, timeout=20).json().get("oclhv", [])
    except Exception:
        return {}
    if not x: return {}
    o = float(x[0]["open"]) or 1e-30
    upto = lambda s: [c for c in x if c["time"] <= int(c0) + s]
    f = {}
    for s in (1, 2):
        cs = upto(s)
        f[f"vol_s{s}"] = round(sum(float(c.get("volume") or 0) for c in cs), 1)
        f[f"px_s{s}"] = round(float(cs[-1]["close"]) / o, 2) if cs else None
    return f

def tweet(r):
    tid = T.tid(r)
    for u in (f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=a", f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&lang=en&token=4"):
        try:
            j = requests.get(u, timeout=6).json()
            us = j.get("user") or {}
            return {"likes": j.get("favorite_count"), "followers": us.get("followers_count"), "verified": bool(us.get("is_blue_verified") or us.get("verified")),
                    "has_media": bool(j.get("mediaDetails") or j.get("photos") or j.get("video")), "text_len": len(j.get("text") or ""),
                    "is_reply": bool(j.get("in_reply_to_status_id_str")), "quote": bool(j.get("quoted_tweet")), "text": (j.get("text") or "")[:100]}
        except Exception:
            continue
    return {}

def med(v):
    v = sorted(x for x in v if x is not None); return v[len(v)//2] if v else None
out = {}
for name, g in (("DECU", picks), ("CONTROL rank1", ctrl)):
    rs = []
    for r in g:
        f = {**early(r), **tweet(r), "rank": r["rank"], "tw2c": r.get("tweet_to_create_s"), "author": r.get("tweet_author"), "sym": r["symbol"]}
        rs.append(f)
    out[name] = rs
    print(f"\n{name} n={len(rs)} | con datos de tweet: {sum(1 for f in rs if f.get('likes') is not None)} | con velas: {sum(1 for f in rs if f.get('px_s2'))}")
    for k in ("vol_s1", "vol_s2", "px_s1", "px_s2", "likes", "followers", "text_len"):
        v = [f.get(k) for f in rs]
        q = sorted(x for x in v if x is not None)
        print(f"  {k:9s} p25 {q[len(q)//4] if q else None} | mediana {med(v)} | p75 {q[3*len(q)//4] if q else None}")
    for k in ("verified", "has_media", "is_reply", "quote"):
        print(f"  {k:9s} {sum(1 for f in rs if f.get(k))}/{len(rs)}")
json.dump(out, open("state/tweet_early.json", "w"))
print("\nmuestra DECU:"); [print("  ", json.dumps({k: f.get(k) for k in ("sym","author","followers","likes","px_s2","vol_s2","text")}, ensure_ascii=False)[:260]) for f in out["DECU"][:12]]
print("muestra CONTROL:"); [print("  ", json.dumps({k: f.get(k) for k in ("sym","author","followers","likes","px_s2","vol_s2","text")}, ensure_ascii=False)[:260]) for f in out["CONTROL rank1"][:8]]
