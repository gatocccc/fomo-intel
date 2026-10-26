"""Guardas operativas: banco por motivo, contadores de rechazos, salida sin datos / fuente caída, escalera de fallas."""
import tempfile
import time
from pathlib import Path

from fomo_intel.live.bot import Bot
from fomo_intel.live.config import LiveParams
from fomo_intel.live.executor import Fill, PaperExecutor
from fomo_intel.live.guard import Bench, Ladder, reason_key
from fomo_intel.live.portfolio import Portfolio


def test_reason_key():
    assert reason_key("seguidor: mcap alto") == "mcap_alto"
    assert reason_key("compra fallida: precio cotizado +40.0% vs referencia (máx 25%)") == "precio_corrido"
    assert reason_key("compra fallida: cotización: x | pumpportal: y") == "compra_fallida"
    assert reason_key("COMPRADO") == "comprado"
    assert reason_key("banco: stop") == "en_banco"


def test_bench_ttl_by_reason_and_persistence():
    with tempfile.TemporaryDirectory() as d:
        b = Bench(Path(d))
        now = 1_000_000.0
        b.add("A", "stop", now)             # 60 min
        b.add("B", "precio_corrido", now)   # 2 min
        b.add("C", "fuente_caida", now)     # 0 = no entra al banco
        assert b.check("A", now + 30 * 60) == "stop"
        assert b.check("B", now + 60) == "precio_corrido"
        assert b.check("B", now + 3 * 60) is None
        assert b.check("C", now) is None
        b2 = Bench(Path(d))                 # sobrevive a un reinicio
        assert b2.check("A", now + 59 * 60) == "stop"
        assert b2.check("A", now + 61 * 60) is None


def test_rejection_counters_survive_restart():
    with tempfile.TemporaryDirectory() as d:
        p = LiveParams()
        port = Portfolio(Path(d), p)
        for _ in range(3):
            port.log_signal({"mint": "X"}, "seguidor: mcap alto")
        port.log_signal({"mint": "Y"}, "COMPRADO")
        snap = Portfolio(Path(d), p).rejections.snapshot()
        assert snap["seen"] == 4 and snap["bought"] == 1 and snap["by_reason"]["mcap_alto"] == 3


def test_ladder_exec_failures():
    lad = Ladder()
    now = 1000.0
    for i in range(4):
        lad.on_fill(False, "buy", "M", "sin confirmación en 75 s", now + i)
    assert lad.exec_fail_burst(5, 600, now + 5) == 0
    lad.on_fill(False, "buy", "M", "precio cotizado +40%", now + 5)    # guardia de precio: no es falla de cañería
    assert lad.exec_fail_burst(5, 600, now + 5) == 0
    lad.on_fill(False, "sell", "M", "swap api 500", now + 6)
    assert lad.exec_fail_burst(5, 600, now + 6) == 5
    assert lad.sell_fails["M"] == 1
    lad.on_fill(True, "sell", "M", "", now + 7)
    assert not lad.exec_fails and lad.sell_fails["M"] == 0


def _bare_bot(d: str, strategy: str = "follow") -> Bot:
    """Bot sin red: solo lo necesario para step_positions."""
    b = Bot.__new__(Bot)
    b.p = LiveParams(); b.p.strategy = strategy; b.p.follow_max_hold_min = 15; b.p.max_hold_min = 15
    b.state = Path(d); b.port = Portfolio(b.state, b.p); b.exe = PaperExecutor(b.p)
    b.bench = Bench(b.state); b.ladder = Ladder()
    b._sell_backoff, b._price_poll, b._poll_fails, b.leaders, b.follow = {}, {}, {}, {}, {}
    b.sol_usd = 180.0; b.helius = None

    class _Stream:
        connected = True
        def snapshot(self, m): return None
        def unpin(self, m): pass

    class _ST:
        def price(self, m): return None          # la API de precios no responde
    b.stream, b.st = _Stream(), _ST()
    return b


def test_exit_when_no_price_data():
    with tempfile.TemporaryDirectory() as d:
        b = _bare_bot(d)
        pos = b.port.open(b.exe.buy("M1", 0.05, 1e-7), "M1", 180.0)
        t0 = pos.opened_ts
        b.step_positions(t0 + 20)                # 1ª consulta fallida: todavía no
        assert "M1" in b.port.positions
        b.step_positions(t0 + 40)                # 2ª fallida, pero sin precio hace solo 40 s
        assert "M1" in b.port.positions
        b.step_positions(t0 + 95)                # 3ª fallida y >90 s sin precio -> cierra
        assert "M1" not in b.port.positions
        assert b.port.closed()[-1]["exits"] == ["sin datos"]
        assert b.bench.check("M1", t0 + 100) == "sin_datos"


def test_exit_when_signal_source_down():
    with tempfile.TemporaryDirectory() as d:
        b = _bare_bot(d)
        b.st.price = lambda m: 1e-7 * 180.0      # hay precio (US$): no es "sin datos"
        pos = b.port.open(b.exe.buy("M2", 0.05, 1e-7), "M2", 180.0)
        t0 = pos.opened_ts
        b.stream.connected = False               # sin Helius, la fuente es PumpPortal
        b.step_positions(t0 + 1)
        assert "M2" in b.port.positions
        b.step_positions(t0 + 62)
        assert "M2" not in b.port.positions
        assert b.port.closed()[-1]["exits"] == ["fuente caída"]
        assert any("fuente" in a for a in b.ladder.alerts)


def test_stop_benches_token():
    with tempfile.TemporaryDirectory() as d:
        b = _bare_bot(d)
        b.st.price = lambda m: (1e-7 * 0.5) * 180.0     # cae 50% -> stop
        pos = b.port.open(b.exe.buy("M3", 0.05, 1e-7), "M3", 180.0)
        b.step_positions(pos.opened_ts + 16)
        assert "M3" not in b.port.positions
        assert b.bench.check("M3") == "stop"


def test_burst_creates_stop_file():
    with tempfile.TemporaryDirectory() as d:
        b = _bare_bot(d)
        for i in range(5):
            b._log_fill(Fill(False, "buy", f"T{i}", error="sin confirmación en 75 s"), "paper", "x", 180.0)
        assert (Path(d) / "STOP").exists()
        assert b.port.stop_reason() == "STOP manual"
