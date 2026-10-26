"""Cazador de tokens de tweet (26/10/2026). Proceso aparte del bot.

Cada token nuevo de pump.fun (Helius, directo de la cadena) -> metadatos -> si su X apunta a un tweet: features del 1er segundo
(volumen y salto de precio, de los TradeEvents en vivo), rango dentro del tweet, demora tweet->token, likes, historial del autor
-> puntaje del modelo (GBM entrenado con el dataset del día, ops 087) -> si supera el umbral, ENTRA.

Modo paper (por defecto): la entrada se registra al precio real del stream 1,5 s después de decidir (+3%), la salida igual que en la
simulación: +100% / -35% / 80 s, con 2% de fees. Modo real: compra por PumpPortal directo (fast) y vende con el mismo criterio.
Control en state/tweetsniper/control.json (mode, size_usd, max_open, total_loss_usd, daily_loss_usd, threshold, enabled).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import pickle
import struct
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import websocket
from solders.pubkey import Pubkey

try:
    from orjson import loads
except ImportError:  # noqa: BLE001
    from json import loads

from .tweet_shadow import decode_create, fetch_meta

log = logging.getLogger("sniper")
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TRADE_D = hashlib.sha256(b"event:TradeEvent").digest()[:8]
CREATE_D = hashlib.sha256(b"event:CreateEvent").digest()[:8]
DIR = Path("state/tweetsniper"); DIR.mkdir(parents=True, exist_ok=True)
CTRL = DIR / "control.json"
DEFAULT_CTRL = {"enabled": True, "mode": "paper", "size_usd": 5.0, "max_open": 3, "total_loss_usd": 25.0, "daily_loss_usd": 25.0,
                "threshold": None, "tp": 1.0, "stop": 0.35, "hold_s": 80, "decide_at_s": 1.0, "paper_slip": 0.03}
FEATS = "vol_s1 px_s1 rank1 rank tw2c web vanity likes verif media quote a_n a_win a_max a_decu j7 uxento".split()


def feat_vector(x: dict) -> list:
    tw2c = x.get("tw2c")
    return [math.log1p(x["vol_s1"]), x["px_s1"] or 1, x["rank"] == 1, min(x["rank"], 20),
            (tw2c if tw2c is not None and 0 <= tw2c < 3600 else 3600) / 60, bool(x["website"]), bool(x["vanity"]),
            math.log1p(x.get("tw_likes") or 0), bool(x.get("tw_verified")), bool(x.get("tw_media")), bool(x.get("tw_quote_author")),
            x.get("a_n", 0), x.get("a_win", 0), x.get("a_max", 0), x.get("a_decu", 0), "j7" in x["tool"], "uxento" in x["tool"]]


def decode_trade(b: bytes):
    if len(b) < 113 or b[:8] != TRADE_D:
        return None
    sol, tok = struct.unpack_from("<QQ", b, 40)
    vsol, vtok = struct.unpack_from("<QQ", b, 97)
    return {"mint": str(Pubkey.from_bytes(b[8:40])), "sol": sol / 1e9, "is_buy": b[56] == 1,
            "price": (vsol / 1e9) / (vtok / 1e6) if vsol and vtok else 0.0}


class Token:
    __slots__ = ("mint", "t0", "slot0", "name", "symbol", "uri", "meta", "feat", "trades", "decided", "first_px", "last_px", "last_ts")

    def __init__(self, mint, t0, c, slot0=0):
        self.mint, self.t0, self.slot0, self.name, self.symbol, self.uri = mint, t0, slot0, c["name"], c["symbol"], c["uri"]
        self.meta = None; self.feat = None; self.trades = []; self.decided = False
        self.first_px = self.last_px = 0.0; self.last_ts = 0.0


class Sniper:
    def __init__(self):
        self.ctrl = self._ctrl()
        m = pickle.load(open(DIR / "model.pkl", "rb"))
        self.model, self.authors = m["model"], m["authors"]
        if self.ctrl.get("threshold") is None:
            self.ctrl["threshold"] = m["threshold"]; json.dump(self.ctrl, open(CTRL, "w"), indent=1)
        self.tokens: dict[str, Token] = {}
        self.rank = defaultdict(int)
        self.pool = ThreadPoolExecutor(48)
        self.lock = threading.Lock()
        self.open: dict[str, dict] = {}
        self.sol_usd = self._sol_usd() or 100.0
        self.stats = defaultdict(int)
        self.exe = None
        if self.ctrl["mode"] == "real":
            from ..live.config import Env, LiveParams
            from ..live.executor import RealExecutor
            from ..live.wallet import Rpc, load_or_create
            env = Env(); p = LiveParams(); p.swap_slippage_pct = 30.0; p.priority_fee_sol = 0.002
            self.exe = RealExecutor(p, load_or_create(env.wallet_file), Rpc(env.rpc_url), env.solanatracker_api_key)
        self._seed_rank()
        self.cur_slot = 0; self.lag_slots = None

    # ---------- utilidades ----------
    def _ctrl(self):
        c = dict(DEFAULT_CTRL)
        try: c.update(json.load(open(CTRL)))
        except Exception: pass  # noqa: BLE001
        json.dump(c, open(CTRL, "w"), indent=1)
        return c

    def _sol_usd(self):
        try:
            r = requests.get("https://data.solanatracker.io/price", params={"token": "So11111111111111111111111111111111111111112"},
                             headers={"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}, timeout=10).json()
            return float(r.get("price") or 0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _seed_rank(self):
        """Rango dentro de cada tweet: sembrado con lo que vio la sombra en las últimas 3 h."""
        f = Path("state/tweetshadow/creates_helius.jsonl")
        if not f.exists():
            return
        cut = time.time() - 3 * 3600
        for l in open(f):
            try:
                r = json.loads(l)
            except Exception:  # noqa: BLE001
                continue
            if r.get("is_tweet") and r["seen_ts"] > cut:
                self.rank[r["twitter"].split("/status/")[1].split("?")[0].split("/")[0]] += 1

    def _log(self, name, row):
        with self.lock:
            with open(DIR / name, "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _closed(self):
        f = DIR / "closed.jsonl"
        return [json.loads(l) for l in open(f)] if f.exists() else []

    # ---------- metadatos y tweet ----------
    def _enrich(self, t: Token):
        meta, lat, src = fetch_meta(t.uri) if t.uri else ({}, 0, "sin uri")
        tw = meta.get("twitter") or ""
        if "/status/" not in tw:
            t.meta = {"is_tweet": False}; return
        tid = tw.split("/status/")[1].split("?")[0].split("/")[0]
        with self.lock:
            self.rank[tid] += 1; rk = self.rank[tid]
        author = tw.split("://")[-1].split("/")[1].lower() if "://" in tw or tw.startswith("x.com") else ""
        try:
            tw2c = t.t0 - ((int(tid) >> 22) + 1288834974657) / 1000
        except ValueError:
            tw2c = None
        a = self.authors.get(author, {})
        t.meta = {"is_tweet": True, "tid": tid, "rank": rk, "author": author, "tw2c": tw2c, "tool": src, "meta_lat": round(lat, 2),
                  "website": bool(meta.get("website")), "vanity": not t.mint.endswith("pump"),
                  "a_n": a.get("n", 0), "a_win": a.get("win", 0), "a_max": a.get("max", 0), "a_decu": a.get("decu", 0)}
        try:
            j = requests.get(f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=a", timeout=2).json()
            t.meta.update({"tw_likes": j.get("favorite_count"), "tw_verified": bool((j.get("user") or {}).get("is_blue_verified")),
                           "tw_media": bool(j.get("mediaDetails") or j.get("photos")), "tw_quote_author": bool(j.get("quoted_tweet")),
                           "tw_text": (j.get("text") or "")[:140]})
        except Exception:  # noqa: BLE001
            pass

    # ---------- decisión ----------
    def _decide(self, t: Token, now: float):
        t.decided = True
        m = t.meta or {}
        if not m.get("is_tweet"):
            self.stats["no_tweet" if t.meta else "sin_meta_a_tiempo"] += 1; return
        w = [x for x in t.trades if x[3] <= t.slot0 + 3]          # ~1,2 s de cadena (3 slots) desde la creación
        vol = sum(x[1] for x in w) * self.sol_usd
        px1 = (w[-1][2] / t.first_px) if (w and t.first_px) else 1.0
        x = {**m, "vol_s1": vol, "px_s1": px1}
        score = float(self.model.predict_proba([feat_vector(x)])[0][1])
        row = {"ts": now, "mint": t.mint, "symbol": t.symbol, "score": round(score, 4), "vol_s1": round(vol), "px_s1": round(px1, 3),
               **{k: m.get(k) for k in ("rank", "author", "tw2c", "tool", "meta_lat", "tw_likes", "tw_text")}}
        self.stats["tweet"] += 1
        thr = self.ctrl["threshold"]
        if score < thr:
            row["decision"] = "bajo umbral"; self._log("decisions.jsonl", row); return
        why = self._stop_reason()
        if why:
            row["decision"] = f"freno: {why}"; self._log("decisions.jsonl", row); return
        row["decision"] = "ENTRA"; self._log("decisions.jsonl", row); self.stats["entra"] += 1
        log.info("ENTRA %s score %.3f vol_s1 US$%.0f px_s1 %.2f autor %s", t.symbol, score, vol, px1, m.get("author"))
        self.pool.submit(self._enter, t, row)

    def _stop_reason(self):
        c = self.ctrl
        if not c.get("enabled", True): return "desactivado"
        if len(self.open) >= c["max_open"]: return "máx abiertas"
        closed = self._closed()
        tot = sum(r["pnl_usd"] for r in closed)
        if tot <= -abs(c["total_loss_usd"]): return "pérdida total"
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 3600))
        if sum(r["pnl_usd"] for r in closed if r.get("day") == today) <= -abs(c["daily_loss_usd"]): return "pérdida del día"
        return None

    def _enter(self, t: Token, row: dict):
        c = self.ctrl
        size_sol = c["size_usd"] / self.sol_usd
        if c["mode"] == "real" and self.exe:
            f = self.exe.buy(t.mint, size_sol, t.last_px, fast=True)
            if not f.ok:
                self._log("trades.jsonl", {"ts": time.time(), "mint": t.mint, "side": "buy", "ok": False, "error": f.error[:200]}); return
            entry, tokens, sol_in = f.price, f.tokens, f.sol
            self._log("trades.jsonl", {"ts": time.time(), "mint": t.mint, "side": "buy", "ok": True, "price": entry, "sol": sol_in, "lat": f.latency_s, "sig": f.sig})
        else:
            time.sleep(1.5)                           # ~ lo que tarda en confirmarse una compra real
            entry = (t.last_px or t.first_px) * (1 + c["paper_slip"]); sol_in = size_sol; tokens = sol_in / entry if entry else 0
        if entry <= 0:
            return
        with self.lock:
            self.open[t.mint] = {"mint": t.mint, "symbol": t.symbol, "t_in": time.time(), "entry": entry, "tokens": tokens, "sol_in": sol_in,
                                 "peak": entry, "score": row["score"], "t0": t.t0, "mode": c["mode"]}

    def _manage(self, now: float):
        c = self.ctrl
        for mint, p in list(self.open.items()):
            t = self.tokens.get(mint)
            px = t.last_px if t else 0
            if px <= 0:
                continue
            p["peak"] = max(p["peak"], px)
            why = ("tp" if px >= p["entry"] * (1 + c["tp"]) else "stop" if px <= p["entry"] * (1 - c["stop"])
                   else "tiempo" if now - p["t_in"] >= c["hold_s"] else None)
            if not why:
                continue
            self.open.pop(mint, None)
            self.pool.submit(self._exit, p, px, why)

    def _exit(self, p, px, why):
        if p["mode"] == "real" and self.exe:
            f = None
            for i in range(3):
                f = self.exe.sell(p["mint"], p["tokens"], px, fast=i > 0)
                if f.ok or "sin tokens" in f.error: break
                time.sleep(2)
            sol_out = f.sol if f and f.ok else 0.0
            self._log("trades.jsonl", {"ts": time.time(), "mint": p["mint"], "side": "sell", "ok": bool(f and f.ok), "sol": sol_out, "error": (f.error if f else "")[:200]})
        else:
            sol_out = p["tokens"] * px * 0.98
        pnl = (sol_out - p["sol_in"]) * self.sol_usd
        row = {"ts": time.time(), "day": time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 3600)), "mint": p["mint"], "symbol": p["symbol"],
               "mode": p["mode"], "why": why, "ret": round(sol_out / p["sol_in"] - 1, 3) if p["sol_in"] else None, "pnl_usd": round(pnl, 2),
               "peak_mult": round(p["peak"] / p["entry"], 2), "hold_s": round(time.time() - p["t_in"]), "entry_age_s": round(p["t_in"] - p["t0"], 1), "score": p["score"]}
        self._log("closed.jsonl", row)
        log.info("SALE %s %s ret %+.0f%% pnl US$%+.2f", p["symbol"], why, (row["ret"] or 0) * 100, pnl)

    # ---------- loop ----------
    def _summary(self):
        closed = self._closed()
        s = {"ts": time.time(), "lag_slots": self.lag_slots, "tokens_tracked": len(self.tokens), "ctrl": self.ctrl, "stats": dict(self.stats), "open": list(self.open.values()), "sol_usd": self.sol_usd,
             "closed": len(closed), "wins": sum(1 for r in closed if (r["ret"] or 0) > 0), "pnl_usd": round(sum(r["pnl_usd"] for r in closed), 2),
             "ret_sum": round(sum(r["ret"] or 0 for r in closed), 3), "last": closed[-8:][::-1]}
        json.dump(s, open("state/tweetsniper_summary.json", "w"), indent=1)

    def run(self):
        url = f"wss://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
        last_tick = last_sum = last_ctrl = 0.0
        while True:
            try:
                ws = websocket.create_connection(url, timeout=5)
                ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe", "params": [{"mentions": [PUMP]}, {"commitment": "processed"}]}))
                log.info("conectado; modo %s umbral %.4f", self.ctrl["mode"], self.ctrl["threshold"])
                while True:
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        raw = None
                    now = time.time()
                    if raw and "Program data" in raw:
                        res = loads(raw).get("params", {}).get("result", {})
                        v = res.get("value", {}); slot = (res.get("context") or {}).get("slot") or 0
                        if slot > self.cur_slot: self.cur_slot = slot
                        if not v.get("err"):
                            self._on_logs(v.get("logs") or [], now, slot)
                    if now - last_tick > 0.2:
                        last_tick = now
                        for t in list(self.tokens.values()):
                            if t.decided or not t.slot0: continue
                            # decidir cuando ya pasaron 4 slots de cadena (los trades del 1er segundo ya se leyeron) y hay metadatos;
                            # sin metadatos a los 12 slots (~5 s): se descarta
                            if self.cur_slot >= t.slot0 + 4 and t.meta is not None:
                                self._decide(t, now)
                            elif self.cur_slot >= t.slot0 + 12:
                                self._decide(t, now)
                        self._manage(now)
                        if len(self.tokens) > 3000:
                            for m in [m for m, t in self.tokens.items() if now - t.t0 > 300 and m not in self.open]:
                                self.tokens.pop(m, None)
                    if now - last_sum > 10:
                        last_sum = now; self._summary()
                        try:
                            rs = requests.post(f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}",
                                               json={"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": [{"commitment": "processed"}]}, timeout=3).json()["result"]
                            self.lag_slots = rs - self.cur_slot
                        except Exception:  # noqa: BLE001
                            pass
                    if now - last_ctrl > 30:
                        last_ctrl = now; mode = self.ctrl["mode"]; self.ctrl = self._ctrl(); self.ctrl["mode"] = mode
                        self.sol_usd = self._sol_usd() or self.sol_usd
            except Exception as e:  # noqa: BLE001
                log.warning("ws caído: %s", str(e)[:120]); time.sleep(2)

    def _on_logs(self, logs, now, slot=0):
        for l in logs:
            if not l.startswith("Program data: "):
                continue
            try:
                b = base64.b64decode(l[14:])
            except Exception:  # noqa: BLE001
                continue
            if b[:8] == CREATE_D:
                c = decode_create(["Program data: " + l[14:]])
                if c and c["mint"] not in self.tokens:
                    t = Token(c["mint"], now, c, slot); self.tokens[c["mint"]] = t
                    self.pool.submit(self._enrich, t)
            elif b[:8] == TRADE_D:
                tr = decode_trade(b)
                if tr:
                    t = self.tokens.get(tr["mint"])
                    if t and tr["price"] > 0:
                        if not t.first_px: t.first_px = tr["price"]
                        t.last_px, t.last_ts = tr["price"], now
                        if slot and t.slot0 and slot <= t.slot0 + 3: t.trades.append((now, tr["sol"], tr["price"], slot))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Sniper().run()


if __name__ == "__main__":
    main()
