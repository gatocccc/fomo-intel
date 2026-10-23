"""Estrategia de lanzamientos: deployers con historial y sus clusters de wallets.

Fuente: Solana Tracker Data API.
  GET /tokens/latest                     -> tokens recién creados (con `deployer`)
  GET /tokens/multi/graduated            -> tokens que completaron la curva (los 'ganadores')
  GET /tokens/{mint}                     -> detalle + risk (snipers, insiders, bundlers), pools (liq, mcap, createdAt)
  GET /tokens/{mint}/bundlers            -> wallets que compraron en bundle en el bloque de creación
  GET /v2/pnl/tokens/{mint}/first-buyers -> primeros compradores en orden cronológico
  GET /v2/pnl/tokens/{mint}/traders      -> por PnL; identity.developer marca al dev

Para cada lanzamiento se guarda un registro `Launch` y se arma el perfil del deployer.
Presupuesto: ~4 requests por token. Plan Free (2.500/mes) = ~600 tokens. Se prioriza
graduados (señal positiva) y una muestra de latest (base) para no sesgar.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

BASE = "https://data.solanatracker.io"


class QuotaExhausted(RuntimeError):
    pass


@dataclass
class Buyer:
    wallet: str
    first_trade_ts: int          # segundos
    invested_usd: float
    proceeds_usd: float
    balance: float
    realized_usd: float
    buys: int
    sells: int
    tags: list[str] = field(default_factory=list)
    is_developer: bool = False


@dataclass
class Launch:
    mint: str
    symbol: str
    deployer: str
    created_ts: int
    graduated: bool
    market_cap_usd: float
    liquidity_usd: float
    sniper_pct: float
    insider_pct: float
    bundler_pct: float
    bundlers: list[str]
    first_buyers: list[Buyer]
    fetched_ts: int
    creation_tx: str = ""
    launchpad: str = ""            # pumpfun | bags | bonk | ... (market del pool de curva)
    rugged: bool = False
    risk_score: int = 0
    top10_pct: float = 0.0
    dev_pct: float = 0.0
    snipers: list[dict] = field(default_factory=list)   # [{wallet, buyTime, balance, percentage}]
    insiders: list[dict] = field(default_factory=list)
    returns: dict = field(default_factory=dict)        # ventana -> {priceChangePercentage, volume, buys, sells}
    holders: int = 0
    partial: bool = False          # True: guardado sin bundlers ni first_buyers (modo barato)


class LaunchFetcher:
    def __init__(self, api_key: str, data_dir: str, sleep_s: float = 0.4):
        if not api_key:
            raise ValueError("SOLANATRACKER_API_KEY vacío")
        self.h = {"x-api-key": api_key}
        self.sleep = sleep_s
        self.dir = Path(data_dir) / "launches"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.requests_made = 0

    def _get(self, path: str, **params):
        r = requests.get(f"{BASE}{path}", headers=self.h, params=params, timeout=30)
        self.requests_made += 1
        time.sleep(self.sleep)
        if r.status_code == 429:
            time.sleep(5)
            r = requests.get(f"{BASE}{path}", headers=self.h, params=params, timeout=30)
            self.requests_made += 1
        if r.status_code == 403:
            raise QuotaExhausted(f"403 en {path}: cuota de Solana Tracker agotada")
        r.raise_for_status()
        return r.json()

    # ---------- listas ----------
    def latest(self) -> list[dict]:
        return self._get("/tokens/latest")

    def graduated(self) -> list[dict]:
        d = self._get("/tokens/multi/graduated")
        return d if isinstance(d, list) else d.get("tokens", d.get("data", []))

    # ---------- un token ----------
    def fetch_launch(self, mint: str, graduated_hint: bool | None = None, cheap: bool = False) -> Launch | None:
        p = self.dir / f"{mint}.json"
        if p.exists():
            d = json.load(open(p))
            d["first_buyers"] = [Buyer(**b) for b in d["first_buyers"]]
            return Launch(**d)
        try:
            info = self._get(f"/tokens/{mint}")
        except requests.HTTPError:
            return None
        raw_dir = self.dir.parent / "launches_raw"
        raw_dir.mkdir(exist_ok=True)
        json.dump(info, open(raw_dir / f"{mint}.json", "w"))
        tk = info.get("token") or {}
        creation = tk.get("creation") or {}
        pools = info.get("pools") or [{}]
        curve = min(pools, key=lambda x: x.get("createdAt") or 9e18)          # el más viejo = curva/lanzamiento
        best = max(pools, key=lambda x: ((x.get("liquidity") or {}).get("usd") or 0))
        created = creation.get("created_time") or curve.get("createdAt") or 0
        created = int(created / 1000) if created > 1e11 else int(created)
        risk = info.get("risk") or {}
        graduated = graduated_hint if graduated_hint is not None else bool(
            len(pools) > 1 or (curve.get("curvePercentage") or 0) >= 100)
        if cheap:
            bundlers, traders = [], []
        else:
          try:
            bl = self._get(f"/tokens/{mint}/bundlers")
            bundlers = [w.get("wallet", w) if isinstance(w, dict) else w for w in (bl.get("wallets", []) if isinstance(bl, dict) else bl)]
          except requests.HTTPError:
            bundlers = []
          traders = self._first_buyers(mint)
        buyers = []
        for t in traders:
            tm = t.get("timing") or {}
            ident = t.get("identity") or {}
            ft = tm.get("firstTrade") or 0
            buyers.append(Buyer(
                wallet=t.get("wallet", ""),
                first_trade_ts=int(ft / 1000) if ft > 1e11 else int(ft),
                invested_usd=float(t.get("invested") or 0),
                proceeds_usd=float(t.get("proceeds") or 0),
                balance=float((t.get("position") or {}).get("balance") or 0),
                realized_usd=float(((t.get("pnl") or {}).get("token") or {}).get("realized") or 0),
                buys=int((t.get("counts") or {}).get("buys") or 0),
                sells=int((t.get("counts") or {}).get("sells") or 0),
                tags=list(ident.get("tags") or []),
                is_developer=bool(ident.get("developer")),
            ))
        ev = info.get("events") or {}
        launch = Launch(
            mint=mint,
            symbol=tk.get("symbol", ""),
            deployer=creation.get("creator") or "",
            created_ts=created,
            graduated=graduated,
            market_cap_usd=float((best.get("marketCap") or {}).get("usd") or 0),
            liquidity_usd=float((best.get("liquidity") or {}).get("usd") or 0),
            sniper_pct=float((risk.get("snipers") or {}).get("totalPercentage") or 0),
            insider_pct=float((risk.get("insiders") or {}).get("totalPercentage") or 0),
            bundler_pct=float((risk.get("bundlers") or {}).get("totalPercentage") or 0),
            bundlers=bundlers,
            first_buyers=buyers,
            fetched_ts=int(time.time()),
            creation_tx=creation.get("created_tx") or "",
            launchpad=(curve.get("market") or "").replace("-curve", ""),
            rugged=bool(risk.get("rugged")),
            risk_score=int(risk.get("score") or 0),
            top10_pct=float(risk.get("top10") or 0),
            dev_pct=float((risk.get("dev") or {}).get("percentage") or 0),
            snipers=[{"wallet": w.get("wallet"), "buy_ts": int((w.get("buyTime") or 0) / 1000), "balance": w.get("balance", 0), "pct": w.get("percentage", 0)}
                     for w in (risk.get("snipers") or {}).get("wallets", [])],
            insiders=[{"wallet": w.get("wallet"), "balance": w.get("balance", 0), "pct": w.get("percentage", 0)}
                      for w in (risk.get("insiders") or {}).get("wallets", [])],
            returns={k: {"chg": (v or {}).get("priceChangePercentage"), "vol": (v or {}).get("volume"),
                         "buys": (v or {}).get("buys"), "sells": (v or {}).get("sells")} for k, v in ev.items()},
            holders=int(info.get("holders") or 0),
            partial=cheap,
        )
        json.dump(asdict(launch), open(p, "w"))
        return launch

    def _first_buyers(self, mint: str) -> list[dict]:
        try:
            return self._get(f"/v2/pnl/tokens/{mint}/first-buyers", limit=100).get("traders", [])
        except requests.HTTPError:
            return []

    def complete_buyers(self, L: Launch) -> Launch:
        """Completa first_buyers de un lanzamiento guardado en modo barato (1 request)."""
        if not L.partial:
            return L
        buyers = []
        for t in self._first_buyers(L.mint):
            tm = t.get("timing") or {}; ident = t.get("identity") or {}; ft = tm.get("firstTrade") or 0
            buyers.append(Buyer(wallet=t.get("wallet", ""), first_trade_ts=int(ft / 1000) if ft > 1e11 else int(ft),
                                invested_usd=float(t.get("invested") or 0), proceeds_usd=float(t.get("proceeds") or 0),
                                balance=float((t.get("position") or {}).get("balance") or 0),
                                realized_usd=float(((t.get("pnl") or {}).get("token") or {}).get("realized") or 0),
                                buys=int((t.get("counts") or {}).get("buys") or 0), sells=int((t.get("counts") or {}).get("sells") or 0),
                                tags=list(ident.get("tags") or []), is_developer=bool(ident.get("developer"))))
        L.first_buyers = buyers; L.partial = False
        json.dump(asdict(L), open(self.dir / f"{L.mint}.json", "w"))
        return L

    def load_all(self) -> list[Launch]:
        out = []
        for p in self.dir.glob("*.json"):
            d = json.load(open(p))
            d["first_buyers"] = [Buyer(**b) for b in d["first_buyers"]]
            out.append(Launch(**d))
        return out


# ---------- análisis ----------
def deployer_profiles(launches: list[Launch]) -> dict[str, dict]:
    """Por deployer: cuántos lanzamientos, cuántos graduaron, patrón de cluster."""
    prof: dict[str, dict] = defaultdict(lambda: {"launches": 0, "graduated": 0, "rugged": 0, "avg_bundlers": 0.0,
                                                 "avg_snipers": 0.0, "avg_insider_pct": 0.0, "avg_mcap": 0.0, "mints": [], "launchpads": []})
    for L in launches:
        if not L.deployer:
            continue
        d = prof[L.deployer]
        d["launches"] += 1
        d["graduated"] += int(L.graduated)
        d["rugged"] += int(L.rugged)
        d["avg_bundlers"] += len(L.bundlers)
        d["avg_snipers"] += len(L.snipers)
        if L.launchpad and L.launchpad not in d["launchpads"]:
            d["launchpads"].append(L.launchpad)
        d["avg_insider_pct"] += L.insider_pct
        d["avg_mcap"] += L.market_cap_usd
        d["mints"].append(L.mint)
    for d in prof.values():
        n = d["launches"]
        for k in ("avg_bundlers", "avg_snipers", "avg_insider_pct", "avg_mcap"):
            d[k] = round(d[k] / n, 2)
        d["grad_rate"] = round(d["graduated"] / n, 3)
        d["rug_rate"] = round(d["rugged"] / n, 3)
    return dict(prof)


def launch_features(L: Launch) -> dict:
    """Features medibles en los primeros minutos (lo que el bot ve en vivo)."""
    fb = sorted(L.first_buyers, key=lambda b: b.first_trade_ts)
    first10 = fb[:10]
    t0 = L.created_ts or (fb[0].first_trade_ts if fb else 0)
    early = [b for b in fb if b.first_trade_ts - t0 <= 60]
    sn = L.snipers
    return {
        "launchpad": L.launchpad,
        "rugged": L.rugged,
        "n_snipers": len(sn),
        "snipers_still_in": sum(1 for w in sn if (w.get("balance") or 0) > 0),
        "sniper_lead_s": (min(w["buy_ts"] for w in sn) - t0) if sn and t0 else None,
        "ret_1h_pct": (L.returns.get("1h") or {}).get("chg"),
        "ret_24h_pct": (L.returns.get("24h") or {}).get("chg"),
        "n_bundlers": len(L.bundlers),
        "n_buyers_first_60s": len(early),
        "usd_first_60s": round(sum(b.invested_usd for b in early), 2),
        "usd_first10": round(sum(b.invested_usd for b in first10), 2),
        "dev_in_first10": any(b.is_developer for b in first10),
        "sniper_pct": L.sniper_pct,
        "insider_pct": L.insider_pct,
        "bundler_pct": L.bundler_pct,
        "early_still_holding": round(sum(1 for b in early if b.balance > 0) / len(early), 2) if early else 0.0,
        "early_realized_usd": round(sum(b.realized_usd for b in early), 2),
    }
