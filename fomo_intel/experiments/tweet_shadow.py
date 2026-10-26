"""Recolector en modo sombra (no compra nada): cada token nuevo de pump.fun con sus metadatos (link de X, web, descripción)
y cuánto tardamos en poder leerlos. Sirve para comparar los tokens "de tweet" que decu compra con los que NO compra.

Hallazgo que lo motiva (ops 075): 56 de 60 compras grandes de decu son tokens cuyo X apunta a un TWEET puntual
(x.com/<cuenta>/status/<id>); el token se crea ~45 s después del tweet y decu compra ~11 s después de la creación.

Fuente de creaciones: PumpPortal subscribeNewToken (gratis). Las compras de decu ya quedan en state/signals.jsonl (bot en follow).
Uso: python -m fomo_intel.experiments.tweet_shadow [SEGUNDOS]   -> state/tweetshadow/creates.jsonl + stats.txt
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import websocket

OUT = Path("state/tweetshadow"); OUT.mkdir(parents=True, exist_ok=True)
q: queue.Queue = queue.Queue()
stats = Counter()
lock = threading.Lock()


GATEWAYS = ["https://pump.mypinata.cloud/ipfs/", "https://gateway.pinata.cloud/ipfs/", "https://dweb.link/ipfs/", "https://ipfs.io/ipfs/",
            "https://w3s.link/ipfs/", "https://nftstorage.link/ipfs/"]


def fetch_meta(uri: str) -> tuple[dict, float, str]:
    """Hasta 3 rondas (0 s, +4 s, +15 s); en IPFS rota gateways. Devuelve (meta, latencia del intento bueno, host o fail)."""
    import random
    t0 = time.time()
    last = ""
    for wait in (0, 4, 15):
        time.sleep(wait)
        urls = [uri]
        if "/ipfs/" in uri:
            cid = uri.split("/ipfs/", 1)[1]
            gs = GATEWAYS[:]; random.shuffle(gs)
            urls = [g + cid for g in gs[:3]] + [uri]
        for u in urls:
            try:
                r = requests.get(u, timeout=4)
                if r.ok:
                    return r.json(), time.time() - t0, u.split("/")[2]
                last = f"{r.status_code}"
            except Exception as e:  # noqa: BLE001
                last = str(e)[:60]
    return {}, time.time() - t0, "fail:" + last


def handle(msg: dict, seen_ts: float) -> None:
    uri = msg.get("uri") or ""
    meta, lat, src = fetch_meta(uri) if uri else ({}, 0.0, "sin uri")
    tw = meta.get("twitter") or ""
    row = {"seen_ts": round(seen_ts, 3), "mint": msg.get("mint"), "name": msg.get("name"), "symbol": msg.get("symbol"),
           "creator": msg.get("traderPublicKey"), "init_sol": msg.get("solAmount"), "mcap_sol": msg.get("marketCapSol"),
           "pool": msg.get("pool"), "uri": uri, "src": "helius" if msg.get("signature") else "pumpportal", "meta_lat_s": round(lat, 2), "meta_src": src,
           "twitter": tw, "website": meta.get("website") or "", "telegram": meta.get("telegram") or "",
           "description": (meta.get("description") or "")[:200], "created_on": meta.get("createdOn") or "",
           "is_tweet": "/status/" in tw}
    if row["is_tweet"]:
        try:
            tid = int(tw.split("/status/")[1].split("?")[0].split("/")[0])
            row["tweet_ts"] = round(((tid >> 22) + 1288834974657) / 1000, 3)
            row["tweet_to_create_s"] = round(seen_ts - row["tweet_ts"], 1)
            row["tweet_author"] = tw.split("://")[-1].split("/")[1].lower()
        except Exception:  # noqa: BLE001
            pass
    with lock:
        with open(OUT / ("creates_helius.jsonl" if msg.get("signature") else "creates.jsonl"), "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        stats["creates"] += 1; stats["tweet"] += row["is_tweet"]; stats["meta_ok"] += bool(meta)
        stats["lat_sum"] += lat


def worker(pool: ThreadPoolExecutor):
    while True:
        msg, ts = q.get()
        pool.submit(handle, msg, ts)


CREATE_DISC = __import__("hashlib").sha256(b"event:CreateEvent").digest()[:8]
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def decode_create(logs: list[str]) -> dict | None:
    """CreateEvent de pump.fun (Create y CreateV2) desde los logs: name, symbol, uri, mint, user. Acepta mints sin sufijo 'pump'."""
    import base64, struct
    from solders.pubkey import Pubkey
    for l in logs:
        if not l.startswith("Program data: "):
            continue
        try:
            b = base64.b64decode(l[14:])
        except Exception:  # noqa: BLE001
            continue
        if b[:8] != CREATE_DISC:
            continue
        try:
            o, strs = 8, []
            for _ in range(3):
                n = struct.unpack_from("<I", b, o)[0]; o += 4
                strs.append(b[o:o + n].decode("utf-8", "replace")); o += n
            mint = str(Pubkey.from_bytes(b[o:o + 32])); o += 64            # mint, bonding_curve
            user = str(Pubkey.from_bytes(b[o:o + 32]))
            return {"name": strs[0], "symbol": strs[1], "uri": strs[2], "mint": mint, "traderPublicKey": user}
        except Exception:  # noqa: BLE001
            return None
    return None


def run_helius(t_end: float):
    import os
    url = f"wss://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
    last_stat = time.time()
    while time.time() < t_end:
        try:
            ws = websocket.create_connection(url, timeout=30)
            ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe", "params": [{"mentions": [PUMP]}, {"commitment": "processed"}]}))
            while time.time() < t_end:
                raw = ws.recv()
                if not raw or "Instruction: Create" not in raw:      # filtro barato antes de parsear (~1.000 avisos/s)
                    continue
                v = json.loads(raw).get("params", {}).get("result", {}).get("value", {})
                if v.get("err"):
                    continue
                c = decode_create(v.get("logs") or [])
                if c:
                    c["signature"] = v.get("signature")
                    q.put((c, time.time()))
                else:
                    stats["create_sin_decodificar"] += 1
                if time.time() - last_stat > 600:
                    last_stat = time.time()
                    with lock:
                        n = max(stats["creates"], 1)
                        line = (f"{time.strftime('%H:%M:%S')} [helius] creados {stats['creates']} | con tweet {stats['tweet']} ({stats['tweet'] / n:.0%}) | "
                                f"metadatos ok {stats['meta_ok'] / n:.0%} | lat media {stats['lat_sum'] / n:.2f}s | sin decodificar {stats['create_sin_decodificar']}")
                    print(line, flush=True); (OUT / "stats.txt").write_text(line + "\n")
        except Exception as e:  # noqa: BLE001
            print("helius caído:", str(e)[:120], flush=True); time.sleep(3)


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 36000
    if len(sys.argv) > 2 and sys.argv[2] == "helius":
        pool = ThreadPoolExecutor(48)
        threading.Thread(target=worker, args=(pool,), daemon=True).start()
        run_helius(time.time() + dur); print("fin", dict(stats), flush=True); return
    t_end = time.time() + dur
    pool = ThreadPoolExecutor(12)
    threading.Thread(target=worker, args=(pool,), daemon=True).start()
    last_stat = time.time()
    while time.time() < t_end:
        try:
            ws = websocket.create_connection("wss://pumpportal.fun/api/data", timeout=30)
            ws.send(json.dumps({"method": "subscribeNewToken"}))
            while time.time() < t_end:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    ws.ping(); continue
                if not raw:
                    continue
                m = json.loads(raw)
                if m.get("txType") == "create" and m.get("mint"):
                    q.put((m, time.time()))
                if time.time() - last_stat > 600:
                    last_stat = time.time()
                    with lock:
                        n = max(stats["creates"], 1)
                        line = (f"{time.strftime('%H:%M:%S')} creados {stats['creates']} | con tweet {stats['tweet']} ({stats['tweet'] / n:.0%}) | "
                                f"metadatos ok {stats['meta_ok'] / n:.0%} | latencia metadatos media {stats['lat_sum'] / n:.2f}s")
                    print(line, flush=True)
                    (OUT / "stats.txt").write_text(line + "\n")
        except Exception as e:  # noqa: BLE001
            print("ws caído:", str(e)[:120], flush=True); time.sleep(3)
    print("fin", dict(stats), flush=True)


if __name__ == "__main__":
    main()
