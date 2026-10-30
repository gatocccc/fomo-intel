"""Radar de noticias + cortos por shock (29/10/2026). Servicio `fomo-radar`, un ciclo por minuto, 24/7.

Por qué existe: el 29/10 a las ~17:50 ART circuló en X la denuncia de salidas anómalas de Binance ("hack") y el mercado cayó
durante horas. El bot no lo vio: solo miraba promedios de 20 días. Una noticia macro no es un juego de velocidad de bloque (eso
está refutado en pump.fun), es un juego de 5 minutos, y 5 minutos sí se pueden ganar.

Qué hace cada minuto:
  1. Lee titulares: RSS públicos (CoinDesk, Cointelegraph, The Block, Decrypt, CryptoSlate), CryptoPanic si hay token,
     X (API v2) si hay bearer. Deduplica por título.
  2. Clasifica cada titular: palabras clave con peso (exchange_risk, hack, regulatory, macro, bullish) y, si hay
     ANTHROPIC_API_KEY, un modelo rápido confirma tipo / dirección / severidad (1–3). Sin clave, solo palabras clave.
  3. Confirma con precio (Hyperliquid, velas de 5 min de SOL y BTC): un shock bajista = noticias bajistas con severidad acumulada
     ≥ 3 en los últimos 90 min Y caída de precio (SOL −1,5% en 1 h, o −2,5% en 4 h, o BTC −1% en 1 h). Sin caída no hay shock:
     las campañas de FUD sin precio detrás no se operan.
  4. Publica state/desk/radar.json (eventos, shock, posición) para el cerebro (que pasa a defensa y no abre memecoins) y la página.
  5. Si RADAR_PERPS=live: con shock activo abre un CORTO de SOL en Jupiter Perps desde la billetera del libro (colateral 7% del libro,
     2x, máx. 2 aperturas por día) y lo gestiona cada minuto: stop si SOL sube 3,5% desde la entrada, toma de ganancia si cae 7%,
     cierre a las 12 h, o cierre cuando el shock se despeja y la posición gana. Con RADAR_PERPS=shadow solo registra lo que haría.
  Registro: state/desk/radar_log.jsonl (eventos y acciones), state/desk/radar_closed.jsonl (cortos cerrados con resultado),
  y una nota en el diario del libro (state/plan_lloyd/auto/) por cada apertura/cierre, para que se vea en /book/.
Uso: python -m fomo_intel.desk.radar [--once]
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

log = logging.getLogger("radar")
HL = "https://api.hyperliquid.xyz/info"
ST = Path("state/desk")
RADAR = ST / "radar.json"
POS = ST / "radar_pos.json"
LOG = ST / "radar_log.jsonl"
CLOSED = ST / "radar_closed.jsonl"
SEEN = ST / "radar_seen.json"
# Billetera que opera los cortos. Por defecto el LABORATORIO (pedido de Gastón 29/10: "usemos esa wallet en distintas estrategias"):
# el corto por noticias es una hipótesis en prueba y se mide ahí antes de tocar el libro. RADAR_WALLET=secrets/plan_lloyd.json para el libro.
WALLET = Path(os.getenv("RADAR_WALLET", "secrets/plan_lab.json"))
PLAN = os.getenv("RADAR_PLAN", "lab")
BOOK_SUMMARY = Path(f"state/plan_{PLAN}_summary.json")
TRADE_AUTO = Path(f"state/plan_{PLAN}/auto")          # notas de aperturas/cierres: diario de la billetera que opera
BOOK_AUTO = Path("state/plan_lloyd/auto")              # notas de shock: diario del libro (el libro pasa a defensa)

FEEDS = [
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("theblock", "https://www.theblock.co/rss.xml"),
    ("decrypt", "https://decrypt.co/feed"),
    ("cryptoslate", "https://cryptoslate.com/feed/"),
    ("bitcoinmagazine", "https://bitcoinmagazine.com/.rss/full/"),
]
# palabras clave → (tipo, dirección, peso). La dirección es el efecto esperado sobre SOL/BTC en las horas siguientes.
KW = [
    (r"\b(hack|hacked|exploit|exploited|drained|stolen|breach)\b", "hack", -1, 2),
    (r"\b(insolven\w*|bank run|halt\w* withdrawals?|withdrawals? (paused|halted|suspended)|proof[- ]of[- ]reserves|outflows?)\b", "exchange_risk", -1, 2),
    (r"\b(binance|coinbase|okx|bybit|kraken|bitget|htx|kucoin|gate\.io)\b", "exchange", 0, 1),
    (r"\b(sec|cftc|doj|lawsuit|charged|indict\w*|ban(ned)?|crackdown|subpoena)\b", "regulatory", -1, 1),
    (r"\b(liquidat\w+|cascade|flash crash|plunge\w*|crash\w*|tumbl\w+|sell-?off|dump\w*)\b", "selloff", -1, 1),
    (r"\b(depeg\w*|collapse\w*|contagion|bankrupt\w*)\b", "contagion", -1, 2),
    (r"\b(tariff\w*|rate hike|hawkish|cpi|inflation surprise|war|strike\w* on)\b", "macro", -1, 1),
    (r"\b(etf approv\w+|approves? (spot )?etf|rate cut|dovish|strategic reserve|all-time high|record inflows?|listing on|lists?)\b", "bullish", 1, 1),
]
NEG_STRONG = {"hack", "exchange_risk", "contagion"}

# Dos piernas de cortos (29/10 21:40, pedido de Gastón ante el hack confirmado de Binance de US$5.800M):
#  - lab:  cualquier shock (rumor + precio). Colateral 35% del lab. Es la prueba de la hipótesis.
#  - book: solo "shock confirmado": al menos una noticia bajista de severidad 3 que el clasificador marque como hecho confirmado
#          (no alegación) + precio. Colateral 15% del libro a 2x; con stop +3,5% la pérdida máxima es ~1% del libro (regla: ≤ 2%).
LEGS = [
    {"name": "lab", "wallet": Path(os.getenv("RADAR_WALLET", "secrets/plan_lab.json")), "plan": os.getenv("RADAR_PLAN", "lab"),
     "coll_frac": float(os.getenv("RADAR_COLL_FRAC", "0.35")), "coll_min": 10.0, "coll_max": 60.0, "require_confirmed": False, "pos_file": ST / "radar_pos.json"},
    {"name": "book", "wallet": Path("secrets/plan_lloyd.json"), "plan": "lloyd",
     "coll_frac": float(os.getenv("RADAR_BOOK_COLL_FRAC", "0.15")), "coll_min": 20.0, "coll_max": 400.0, "require_confirmed": True, "pos_file": ST / "radar_pos_book.json"},
]
RULES = {"window_min": 90, "min_bear_score": 3, "sol_1h": -0.015, "sol_4h": -0.025, "btc_1h": -0.01,
         "clear_quiet_h": 3, "coll_frac": float(os.getenv("RADAR_COLL_FRAC", "0.35")), "coll_min": 10.0, "coll_max": 60.0, "lev": 2.0,
         "stop_up": 0.035, "tp_down": 0.12, "trail_arm": 0.04, "trail_gap": 0.02, "max_h": 12, "max_opens_day": 2, "cooldown_h": 2, "min_profit_clear": 0.5}
# tp_down pasó de 7% a 12% y se agregó trailing (29/10 noche): con un hack confirmado la caída puede ser larga; en cuanto el corto gana
# trail_arm (4% del precio) se protege trail_gap (2%) desde el mejor punto, en vez de cortar a un objetivo fijo.


def jload(p, d):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def jsave(p, o):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp"); json.dump(o, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def logrow(kind, **kw):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps({"ts": time.time(), "kind": kind, **kw}, ensure_ascii=False) + "\n")


def book_note(title, text, where=None):
    """Nota en el diario público (el motor la registra; sin órdenes). Shock → libro; operaciones → billetera que opera."""
    d = where or BOOK_AUTO
    did = f"auto-{d.parent.name}-radar-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    jsave(d / f"{did}.json", {"id": did, "title": title, "journal": text, "orders": [], "auto": True})


# ------------------------------------------------------------ fuentes
def fetch_rss(name, url):
    out = []
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (fomo-radar)"})
        if not r.ok:
            return out
        root = ET.fromstring(r.content)
        for it in root.iter():
            if it.tag.endswith("item") or it.tag.endswith("entry"):
                title = next((c.text for c in it if c.tag.endswith("title") and c.text), None)
                link = next((c.text or c.attrib.get("href") for c in it if c.tag.endswith("link")), None)
                pub = next((c.text for c in it if c.tag.endswith("pubDate") or c.tag.endswith("published") or c.tag.endswith("updated")), None)
                if title:
                    out.append({"src": name, "title": title.strip(), "link": link, "pub": pub})
    except Exception as e:  # noqa: BLE001
        log.debug("rss %s: %s", name, e)
    return out[:40]


def fetch_cryptopanic():
    tok = os.getenv("CRYPTOPANIC_TOKEN", "")
    if not tok:
        return []
    try:
        r = requests.get("https://cryptopanic.com/api/v1/posts/", params={"auth_token": tok, "filter": "important", "public": "true"}, timeout=15)
        return [{"src": "cryptopanic", "title": x.get("title", ""), "link": x.get("url"), "pub": x.get("published_at")} for x in (r.json().get("results") or [])[:40]]
    except Exception as e:  # noqa: BLE001
        log.debug("cryptopanic: %s", e); return []


def fetch_x():
    tok = os.getenv("X_BEARER_TOKEN", "")
    if not tok:
        return []
    q = "(binance OR coinbase OR solana OR bitcoin) (hack OR hacked OR exploit OR insolvent OR outflows OR halted OR drained OR \"bank run\") -is:retweet lang:en"
    try:
        r = requests.get("https://api.twitter.com/2/tweets/search/recent", params={"query": q, "max_results": 50, "tweet.fields": "created_at,public_metrics"},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        out = []
        for t in (r.json().get("data") or []):
            pm = t.get("public_metrics") or {}
            if (pm.get("like_count") or 0) + (pm.get("retweet_count") or 0) * 3 < 20:
                continue   # solo tweets con tracción
            out.append({"src": "x", "title": t.get("text", "")[:240].replace("\n", " "), "link": None, "pub": t.get("created_at")})
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("x: %s", e); return []


# ------------------------------------------------------------ clasificación
def classify_kw(title):
    t = title.lower(); types, score, direction = [], 0, 0
    for pat, typ, d, w in KW:
        if re.search(pat, t):
            types.append(typ); score += w; direction += d * w
    if not types or types == ["exchange"]:
        return None
    strong = any(x in NEG_STRONG for x in types) and "exchange" in types
    sev = 3 if (strong and score >= 4) else 2 if (strong or score >= 3) else 1
    return {"types": sorted(set(types)), "dir": -1 if direction < 0 else 1 if direction > 0 else 0, "sev": sev, "by": "kw"}


_llm = None


def classify_llm(title):
    """Confirmación con un modelo rápido (opcional). Devuelve None si no hay clave o falla."""
    global _llm
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        if _llm is None:
            import anthropic
            _llm = anthropic.Anthropic()
        msg = _llm.messages.create(
            model=os.getenv("RADAR_LLM_MODEL", "claude-haiku-5-5"), max_tokens=80,
            messages=[{"role": "user", "content": (
                "Crypto market headline. Reply with JSON only: {\"type\": one of [hack, exchange_risk, regulatory, macro, selloff, bullish, noise], "
                "\"dir\": -1 bearish for SOL/BTC in the next hours, 0 neutral, 1 bullish, \"sev\": 1 minor, 2 significant, 3 major/confirmed, "
                "\"confirmed\": true if the headline states a confirmed event rather than a rumour or allegation}. Headline: " + title[:300])}])
        txt = msg.content[0].text
        j = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        if j.get("type") == "noise":
            return {"types": ["noise"], "dir": 0, "sev": 0, "by": "llm"}
        return {"types": [j.get("type")], "dir": int(j.get("dir", 0)), "sev": int(j.get("sev", 1)), "confirmed": bool(j.get("confirmed")), "by": "llm"}
    except Exception as e:  # noqa: BLE001
        log.debug("llm: %s", e); return None


# ------------------------------------------------------------ precio
def hl_candles(coin, interval="5m", hours=6):
    end = int(time.time() * 1000)
    try:
        r = requests.post(HL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": end - hours * 3600000, "endTime": end}}, timeout=15)
        return [(int(c["t"]) // 1000, float(c["c"])) for c in (r.json() if r.ok else [])]
    except Exception as e:  # noqa: BLE001
        log.warning("hyperliquid %s: %s", coin, e); return []


def price_state():
    out = {}
    for coin in ("SOL", "BTC"):
        cs = hl_candles(coin)
        if len(cs) < 50:
            continue
        px = cs[-1][1]
        out[coin] = {"px": px, "ch15m": px / cs[-4][1] - 1, "ch1h": px / cs[-13][1] - 1, "ch4h": px / cs[-49][1] - 1}
    return out


# ------------------------------------------------------------ radar
class Radar:
    def __init__(self):
        self.seen = jload(SEEN, {})          # título normalizado → {ts, cls}
        self.state = jload(RADAR, {"shock": None, "events": []})
        self.mode = os.getenv("RADAR_PERPS", "shadow")
        self._perps = {}
        for leg in LEGS:
            leg["pos"] = jload(leg["pos_file"], None)
        self.legs = LEGS
        self.pos = self.legs[0]["pos"]   # compat: la pierna del lab es la "principal" en radar.json

    # ----- noticias -----
    def ingest(self):
        items = []
        for name, url in FEEDS:
            items += fetch_rss(name, url)
        items += fetch_cryptopanic() + fetch_x()
        now = time.time(); new = []
        for it in items:
            key = re.sub(r"[^a-z0-9]+", " ", it["title"].lower()).strip()[:120]
            if not key or key in self.seen:
                continue
            cls = classify_kw(it["title"])
            if cls:
                llm = classify_llm(it["title"])
                if llm:
                    if "noise" in llm["types"]:
                        cls = None
                    else:
                        cls = {**cls, "types": sorted(set(cls["types"]) | set(llm["types"])), "dir": llm["dir"] or cls["dir"],
                               "sev": max(cls["sev"], llm["sev"]) if llm.get("confirmed") else min(cls["sev"], max(1, llm["sev"])), "by": "kw+llm", "confirmed": llm.get("confirmed")}
            self.seen[key] = {"ts": now, "src": it["src"], "title": it["title"][:200], "cls": cls}
            if cls:
                new.append(self.seen[key]); logrow("event", **self.seen[key])
                log.info("evento [%s] sev %s dir %s: %s", it["src"], cls["sev"], cls["dir"], it["title"][:100])
        # olvidar lo viejo
        self.seen = {k: v for k, v in self.seen.items() if now - v["ts"] < 48 * 3600}
        jsave(SEEN, self.seen)
        return new

    def recent(self, minutes):
        now = time.time()
        return [v for v in self.seen.values() if v.get("cls") and now - v["ts"] <= minutes * 60]

    # ----- shock -----
    def update_shock(self, px):
        R = RULES; now = time.time()
        ev = self.recent(R["window_min"])
        bear = sum(e["cls"]["sev"] for e in ev if e["cls"]["dir"] < 0)
        bull = sum(e["cls"]["sev"] for e in ev if e["cls"]["dir"] > 0)
        sol, btc = px.get("SOL") or {}, px.get("BTC") or {}
        price_conf = (sol.get("ch1h", 0) <= R["sol_1h"]) or (sol.get("ch4h", 0) <= R["sol_4h"]) or (btc.get("ch1h", 0) <= R["btc_1h"])
        strong = any(e["cls"]["sev"] >= 2 for e in ev if e["cls"]["dir"] < 0)   # al menos una noticia bajista de peso, no solo ruido de sev 1
        sh = self.state.get("shock")
        if not sh and bear >= R["min_bear_score"] and strong and bear > bull and price_conf:
            heads = [e["title"] for e in ev if e["cls"]["dir"] < 0][:4]
            sh = {"since": now, "bear_score": bear, "sol_px": sol.get("px"), "btc_px": btc.get("px"), "headlines": heads, "confirmed": self.confirmed_major(ev),
                  "why": f"bearish news score {bear} in {R['window_min']} min; SOL 1h {sol.get('ch1h', 0):+.1%}, 4h {sol.get('ch4h', 0):+.1%}; BTC 1h {btc.get('ch1h', 0):+.1%}"}
            self.state["shock"] = sh; logrow("shock_on", **sh)
            log.warning("SHOCK ON: %s", sh["why"])
            book_note("Radar: market shock detected",
                      f"Lloyd's news radar sees a bearish shock: {sh['why']}. Headlines: " + " | ".join(heads) +
                      ". The book goes defensive (no new memecoins) while it lasts" + (" and looks for a small SOL short." if self.mode == "live" else "."))
        elif sh:
            if not sh.get("confirmed") and self.confirmed_major(ev):
                sh["confirmed"] = True; sh["confirmed_ts"] = now
                # 30/10: al confirmar, los titulares y el "por qué" pasan a ser los del hecho confirmado y el precio de ahora (antes la nota
                # del corto del libro citaba los titulares del arranque del shock — Polymarket, la CFTC — y no el hack de Binance).
                hard = sorted([e for e in ev if e["cls"]["dir"] < 0 and e["cls"]["sev"] >= 2], key=lambda e: (-e["cls"]["sev"], -e["ts"]))
                if hard:
                    sh["headlines"] = [e["title"] for e in hard][:4]
                sh["why"] = (f"confirmed: {len(hard)} major bearish reports in {R['window_min']} min; SOL 1h {sol.get('ch1h', 0):+.1%}, "
                             f"4h {sol.get('ch4h', 0):+.1%}; BTC 1h {btc.get('ch1h', 0):+.1%}")
                logrow("shock_confirmed", **{k: v for k, v in sh.items() if k != "headlines"})
                log.warning("SHOCK CONFIRMADO (noticia de severidad 3 confirmada)")
            quiet = not [e for e in self.recent(R["clear_quiet_h"] * 60) if e["cls"]["dir"] < 0]
            recovered = sol.get("px") and sh.get("sol_px") and sol["px"] >= sh["sol_px"] * 1.01
            if (quiet and now - sh["since"] > 3600) or recovered:
                logrow("shock_off", since=sh["since"], quiet=quiet, recovered=bool(recovered))
                log.warning("SHOCK OFF (quiet=%s recovered=%s)", quiet, recovered)
                self.state["shock"] = None; self.state["last_shock"] = {**sh, "until": now}
        self.state.update({"ts": now, "bear_score": bear, "bull_score": bull, "price": px, "mode": self.mode,
                           "events": [{"ts": e["ts"], "src": e["src"], "title": e["title"], "sev": e["cls"]["sev"], "dir": e["cls"]["dir"], "types": e["cls"]["types"]}
                                      for e in sorted(self.recent(240), key=lambda x: -x["ts"])[:25]],
                           "position": self.pos})

    @staticmethod
    def confirmed_major(ev):
        """Hecho confirmado, no alegación: una noticia bajista de severidad 3 marcada como confirmada por el clasificador, o bien
        ≥ 4 noticias bajistas de severidad ≥ 2 en la ventana (varios medios publicando el mismo hecho = ya no es un rumor de X)."""
        bear2 = [e for e in ev if e["cls"]["dir"] < 0 and e["cls"]["sev"] >= 2]
        return any(e["cls"]["sev"] >= 3 and e["cls"].get("confirmed") for e in bear2) or len(bear2) >= 4

    # ----- perps -----
    def perps(self, leg):
        if leg["name"] not in self._perps:
            from ..live.config import Env
            from ..live.perps import JupPerps
            from ..live.wallet import Rpc, load_or_create
            kp = load_or_create(leg["wallet"]); self._perps[leg["name"]] = JupPerps(kp, Rpc(Env().rpc_url), log)
        return self._perps[leg["name"]]

    @staticmethod
    def plan_equity(plan):
        return (jload(Path(f"state/plan_{plan}_summary.json"), {}) or {}).get("equity_usd") or 0.0

    def manage(self, px):
        sol = (px.get("SOL") or {}).get("px")
        if not sol:
            return
        for leg in self.legs:
            try:
                self.manage_leg(leg, sol)
            except Exception as e:  # noqa: BLE001
                log.exception("pierna %s: %s", leg["name"], e)
        self.pos = self.legs[0]["pos"]

    def manage_leg(self, leg, sol):
        R = RULES; now = time.time()
        sh = self.state.get("shock")
        p = leg["pos"]
        if p:   # gestionar
            ret = 1 - sol / p["entry"]            # ganancia del corto como fracción del precio
            p["best_ret"] = max(p.get("best_ret", 0.0), ret)
            p.update({"mark": sol, "ret_px": round(ret, 4), "pnl_usd_est": round(ret * p["size_usd"], 2), "age_h": round((now - p["ts"]) / 3600, 2)})
            why = None
            if sol >= p["entry"] * (1 + R["stop_up"]): why = f"stop: SOL +{R['stop_up']:.1%} above entry"
            elif p["best_ret"] >= R["trail_arm"] and ret <= p["best_ret"] - R["trail_gap"]: why = f"trailing: locked {ret:.1%} after a best of {p['best_ret']:.1%}"
            elif sol <= p["entry"] * (1 - R["tp_down"]): why = f"take profit: SOL −{R['tp_down']:.0%}"
            elif now - p["ts"] > R["max_h"] * 3600: why = f"time stop ({R['max_h']}h)"
            elif not sh and ret * p["size_usd"] >= R["min_profit_clear"] and now - p["ts"] > 1800: why = "shock cleared with the short in profit"
            if why:
                self.close(leg, why, sol)
            else:
                jsave(leg["pos_file"], p)
            return
        if not sh or (leg["require_confirmed"] and not sh.get("confirmed")):
            return
        today = time.strftime("%Y-%m-%d", time.gmtime(now - 3 * 3600))
        rows = [c for c in self.closed_rows() if c.get("leg", "lab") == leg["name"]]
        opens = [c for c in rows if time.strftime("%Y-%m-%d", time.gmtime(c["ts_open"] - 3 * 3600)) == today]
        last_close = max([c["ts"] for c in rows] or [0])
        if len(opens) >= R["max_opens_day"] or now - last_close < R["cooldown_h"] * 3600:
            return
        eq = self.plan_equity(leg["plan"])
        coll = max(leg["coll_min"], min(leg["coll_max"], eq * leg["coll_frac"]))
        self.open(leg, coll, sol, sh)

    def closed_rows(self):
        if not CLOSED.exists():
            return []
        return [json.loads(l) for l in CLOSED.read_text().splitlines() if l.strip()]

    def open(self, leg, coll, sol, sh):
        R = RULES; now = time.time()
        rec = {"ts": now, "leg": leg["name"], "plan": leg["plan"], "symbol": "SOL", "side": "short", "entry": sol, "collateral_usd": round(coll, 2), "lev": R["lev"], "size_usd": round(coll * R["lev"], 2),
               "mode": self.mode, "why": sh["why"] + (" + confirmed major news" if sh.get("confirmed") else ""), "headlines": sh.get("headlines", [])[:3], "pubkey": None, "sig": None, "best_ret": 0.0}
        if self.mode == "live":
            try:
                r = self.perps(leg).open("SOL", "short", coll, R["lev"], dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                logrow("open_failed", leg=leg["name"], error=str(r.get("error"))[:300], coll=coll); log.error("[%s] short no abrió: %s", leg["name"], r.get("error")); return
            rec.update({"pubkey": r.get("position_pubkey"), "sig": r.get("sig")})
            try:
                live = [q for q in self.perps(leg).positions() if q.get("pubkey") == rec["pubkey"]]
                if live and live[0].get("entry"): rec["entry"] = float(live[0]["entry"])
            except Exception:  # noqa: BLE001
                pass
        leg["pos"] = rec; jsave(leg["pos_file"], rec); logrow("open", **rec)
        log.warning("[%s] SHORT SOL abierto (%s): colateral %.2f, 2x, entrada %.2f", leg["name"], self.mode, coll, rec["entry"])
        where = Path(f"state/plan_{leg['plan']}/auto")
        book_note("Radar: SOL short opened" + ("" if self.mode == "live" else " (shadow)"),
                  f"{'Confirmed' if sh.get('confirmed') else 'Bearish'} news shock with price confirmation ({sh['why']}). Lloyd opens a SOL short on Jupiter Perps: ${coll:.0f} collateral at 2x "
                  f"(${coll * R['lev']:.0f} notional), entry ${rec['entry']:.2f}. Exit: stop if SOL rises {R['stop_up']:.1%}; once the short is up {R['trail_arm']:.0%} it trails {R['trail_gap']:.0%} "
                  f"from its best; take profit at −{R['tp_down']:.0%}; or {R['max_h']}h. Risk if stopped: about ${coll * R['lev'] * R['stop_up']:.1f}. Against: a denial or an exchange backstop can squeeze shorts fast; the stop is tight for that reason.",
                  where=where)

    def close(self, leg, why, sol):
        p = leg["pos"]; now = time.time()
        if p.get("mode") == "live" and p.get("pubkey"):
            try:
                r = self.perps(leg).close(p["pubkey"], dry=False)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if not r.get("ok"):
                logrow("close_failed", leg=leg["name"], error=str(r.get("error"))[:300]); log.error("[%s] cierre falló: %s", leg["name"], r.get("error"))
                p["close_attempts"] = p.get("close_attempts", 0) + 1; jsave(leg["pos_file"], p)
                if p["close_attempts"] < 5:
                    return
        ret = 1 - sol / p["entry"]; pnl = ret * p["size_usd"] - p["size_usd"] * 0.0012 * 2
        row = {"ts": now, "ts_open": p["ts"], "leg": leg["name"], "symbol": "SOL", "side": "short", "entry": p["entry"], "exit": sol, "collateral_usd": p["collateral_usd"],
               "size_usd": p["size_usd"], "ret_px": round(ret, 4), "best_ret": round(p.get("best_ret", 0), 4), "pnl_usd": round(pnl, 2), "hold_h": round((now - p["ts"]) / 3600, 2), "why": why,
               "mode": p.get("mode"), "reason": "news_shock_short"}
        with open(CLOSED, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        logrow("close", **row); log.warning("[%s] SHORT cerrado: %s → %+.2f US$ (%s)", leg["name"], why, pnl, p.get("mode"))
        book_note("Radar: SOL short closed" + ("" if p.get("mode") == "live" else " (shadow)"),
                  f"Closed the SOL short: {why}. Entry ${p['entry']:.2f}, exit ${sol:.2f}, result about ${pnl:+.2f} on ${p['collateral_usd']:.0f} collateral.",
                  where=Path(f"state/plan_{leg['plan']}/auto"))
        leg["pos"] = None
        if leg["pos_file"].exists(): leg["pos_file"].unlink()

    # ----- ciclo -----
    def cycle(self):
        self.ingest()
        px = price_state()
        self.update_shock(px)
        try:
            self.manage(px)
        except Exception as e:  # noqa: BLE001
            log.exception("manage: %s", e)
        self.state["position"] = self.pos
        self.state["positions"] = {leg["name"]: leg["pos"] for leg in self.legs}
        jsave(RADAR, self.state)

    def run(self, once=False):
        while True:
            t0 = time.time()
            try:
                self.cycle()
            except Exception as e:  # noqa: BLE001
                log.exception("ciclo: %s", e)
            if once:
                return
            time.sleep(max(10, 60 - (time.time() - t0)))


def main():
    from ..live.bot import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Radar().run(once="--once" in sys.argv)


if __name__ == "__main__":
    main()
