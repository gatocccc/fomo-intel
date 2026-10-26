"""Entrena el modelo del cazador con state/tweet_dataset.json (mismas features que en vivo) y guarda state/tweetsniper/model.pkl."""
import json, pickle, numpy as np, requests, os, time
from collections import defaultdict
from sklearn.ensemble import HistGradientBoostingClassifier
from fomo_intel.experiments.tweet_sniper import feat_vector, DIR
d = json.load(open("state/tweet_dataset.json")); d.sort(key=lambda x: x["ts"])
d = [x for x in d if x.get("ret_s2") is not None]
hist = defaultdict(list)
for x in d:
    h = [p for p in hist[x["author"]] if x["ts"] - p["ts"] > 200]
    x["a_n"] = len(h); x["a_win"] = sum(p["ret_s2"] > 0 for p in h); x["a_max"] = max([p["max_200"] or 0 for p in h], default=0); x["a_decu"] = sum(p["decu"] for p in h)
    hist[x["author"]].append(x)
X = np.array([feat_vector(x) for x in d], float); y = np.array([x["ret_s2"] > 0 for x in d])
m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=4, random_state=0).fit(X, y)
s = m.predict_proba(X)[:, 1]; thr = float(np.quantile(s, 0.99))
authors = {a: {"n": len(v), "win": sum(p["ret_s2"] > 0 for p in v), "max": max([p["max_200"] or 0 for p in v], default=0), "decu": sum(p["decu"] for p in v)} for a, v in hist.items()}
pickle.dump({"model": m, "threshold": thr, "authors": authors, "trained_on": len(d), "ts": time.time()}, open(DIR / "model.pkl", "wb"))
print(f"modelo entrenado con {len(d)} tokens | umbral (top 1%) {thr:.4f} | autores {len(authors)}")
# unidades del volumen de las velas: comparar con trades de ST del mismo token (en SOL y US$)
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
for x in sorted(d, key=lambda x: -x["vol_s1"])[:4]:
    tr = requests.get(f"https://data.solanatracker.io/trades/{x['mint']}", headers=H, params={"sortDirection": "ASC"}, timeout=20).json()
    rows = tr.get("trades", []) if isinstance(tr, dict) else []
    t0 = int(x["ts"])
    s1 = [r for r in rows if r.get("time", 0) / 1000 <= t0 + 1]
    print(f"  {x['symbol']}: vela vol_s1={x['vol_s1']} | trades ST hasta seg1: n={len(s1)} US$={sum(r.get('volume',0) for r in s1):.0f} SOL={sum(r.get('solVolume',0) or 0 for r in s1):.2f} | primeros: {[ (round(r.get('time',0)/1000-t0,2), r.get('volume')) for r in rows[:4]]}")
