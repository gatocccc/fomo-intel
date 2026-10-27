"""Motor de la mesa sin red: compra por decisión, escalera de ventas, trailing, stop, piso, una sola ejecución por decisión."""
import json, os, time
from pathlib import Path
import pytest
from fomo_intel.desk import engine as E
from fomo_intel.live.executor import Fill


class FakeExe:
    def __init__(self, d): self.d = d
    def buy(self, mint, sol, ref, fast=False):
        px = self.d.px[mint] / self.d.sol_usd
        return Fill(True, "buy", mint, sol=sol, tokens=sol / px, price=px)
    def sell(self, mint, tokens, ref, fast=False):
        px = self.d.px[mint] / self.d.sol_usd
        self.d.wallet += tokens * px
        return Fill(True, "sell", mint, sol=tokens * px, tokens=tokens, price=px)


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(E, "ST_DIR", tmp_path / "state/desk"); (tmp_path / "state/desk").mkdir(parents=True)
    monkeypatch.setattr(E, "DEC", tmp_path / "desk/decisions"); (tmp_path / "desk/decisions").mkdir(parents=True)
    monkeypatch.setattr(E, "WEB", tmp_path / "web/desk.json")
    d = E.Desk.__new__(E.Desk)
    d.cfg = {**E.CFG_DEFAULT, "start_ts": time.time(), "start_usd": 100.0, "start_sol": 1.0}
    d.sol_usd = 100.0; d.px = {"TOK": 1.0}; d.wallet = 1.0
    d.st = type("S", (), {"price": lambda s, m: d.px.get(m), "sol_usd": lambda s, *a: 100.0})()
    d.rpc = type("R", (), {"sol_balance": lambda s, pub: d.wallet})()
    d.pub = "x"; d.exe = FakeExe(d); d.pos = {}; d.processed = []; d.prices = {}; d.no_price_since = {}; d.wallet_sol = 1.0
    return d


def decide(d, did, orders):
    json.dump({"id": did, "journal": "test", "orders": orders}, open(E.DEC / f"{did}.json", "w"))
    d.apply_decisions()


def test_buy_once_tp_and_trailing(desk):
    decide(desk, "a", [{"action": "buy", "mint": "TOK", "symbol": "TOK", "sol": 0.4, "stop": 0.3, "trail": 0.3, "trail_after": 1.5, "tp": [[2, 0.5]]}])
    desk.apply_decisions()                                   # no repite
    assert len(desk.pos) == 1 and abs(desk.pos["TOK"]["sol_in"] - 0.4) < 1e-9
    desk.px["TOK"] = 2.1; desk.protect()                     # toma 50% a 2x
    assert abs(desk.pos["TOK"]["tokens"] - desk.pos["TOK"]["tokens_initial"] * 0.5) < 1e-6
    desk.px["TOK"] = 3.0; desk.protect()                     # pico 3x
    desk.px["TOK"] = 2.0; desk.protect()                     # -33% del pico -> trailing cierra
    assert "TOK" not in desk.pos
    rows = E.tail("closed.jsonl"); assert rows[-1]["ret"] > 0.9


def test_stop_and_floor(desk):
    decide(desk, "b", [{"action": "buy", "mint": "TOK", "symbol": "TOK", "sol": 0.5, "stop": 0.3}])
    desk.px["TOK"] = 0.65; desk.protect()
    assert "TOK" not in desk.pos and E.tail("closed.jsonl")[-1]["why"].startswith("stop")
    desk.floor_check(10.0)
    assert (E.ST_DIR / "HALT").exists()
    decide(desk, "c", [{"action": "buy", "mint": "TOK", "symbol": "TOK", "sol": 0.1}])
    assert "TOK" not in desk.pos                              # detenida: no compra
