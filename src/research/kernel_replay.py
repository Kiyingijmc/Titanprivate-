"""Kernel replay router (Plan 06 / Task 3) — the research <-> live parity seam.

Generalizes the fixture pattern in scripts/capture_parity_golden.py (STUDY,
DO NOT MODIFY that file) into a reusable driver: a `SystemController` built
via `__new__` with the EXACT live kernel attached (real FeatureBus + smc
pack, real Arbiter, real SignalGrader), stubbed only where the harness stubs
it (logger, time engine, market-data store, `_execute_signal`). Strategies
and config are parameters instead of being hardcoded to SilverBullet +
config/config.yaml, so any research driver — offline/"research-status"
strategy instances included — runs through the identical code path
`SystemController._run_strategies` uses live, with the Arbiter genuinely on
the path (IntentEmitted/IntentBlocked are collected, not bypassed).

Purity: no wall clock (the time engine returns a fixed `ny_time` string) and
no I/O beyond reading the `df_h1` frame handed to `replay()`.
"""
import asyncio

import pandas as pd

from src.core.system_controller import SystemController
from src.analysis.signal_grader import SignalGrader
from src.analysis.bias_engine import BiasEngine
from src.features.feature_bus import FeatureBus
from src.features.packs.smc_pack import register_smc_pack
from src.arbiter.arbiter import Arbiter

# Element schema shared with tests/backtest/fixtures/parity_golden_h1.json
# (see scripts/capture_parity_golden.py::capture_stream). SignalRecord adds
# "time" and "strategy" on top.
GOLDEN_FIELDS = ("i", "bias", "signal", "price", "sl", "tp", "grade")


class _StubLogger:
    """No-op logger satisfying log_event(type, module, msg, payload=...)."""

    def log_event(self, *args, **kwargs):
        pass


class _StubTimeEngine:
    """Fixed NY-time string; format must match TimeNormalizer.get_current_ny_string()
    ("%H:%M:%S %Z") since SilverBullet parses the hour via
    int(ny_time_str.split(':')[0]) — see src/analysis/time_math.py:98-102."""

    def __init__(self, ny_time):
        self._ny_time = ny_time

    def get_current_ny_string(self):
        return self._ny_time


class _StubStore:
    """Stand-in for MultiTimeframeStore: only get_data("H1") is exercised by
    _run_strategies (for the bias context)."""

    def __init__(self, h1_df=None):
        self.h1_df = h1_df

    def get_data(self, tf):
        if tf == "H1":
            return self.h1_df
        return None


def build_research_controller(strategies, config, ny_time="10:00:00 EST"):
    """Build a minimal SystemController fixture (no __init__, no bridge/IO)
    with the live kernel attached: real FeatureBus + smc pack, real
    Arbiter(config['arbiter'], publish=<collector>), real SignalGrader
    (config). `strategies` are injected directly (already-constructed
    instances) — no promote-gate/registry involvement, so research-status
    strategies work exactly like sanctioned ones.

    Mirrors scripts/capture_parity_golden.py::_make_controller, generalized:
    parameterized strategies/config, and the FeatureBus/Arbiter attachment is
    unconditional (this module targets the current, post-refactor kernel —
    no pre-refactor ImportError fallback).

    Returns (controller, captured, published):
      captured  -- list the stubbed _execute_signal appends
                   (symbol, decision, name, htf_bias, grade) to.
      published -- list every event the Arbiter emits (IntentEmitted /
                   IntentBlocked) is appended to, in emission order.
    """
    logger = _StubLogger()

    c = SystemController.__new__(SystemController)
    c.config = config
    c.logger = logger
    c.strategies = list(strategies)
    c.signal_grader = SignalGrader(config)
    c.time_engine = _StubTimeEngine(ny_time)
    c.market_data = {}

    captured = []

    async def _capture_execute_signal(symbol, decision, name, htf_bias, grade=""):
        captured.append((symbol, decision, name, htf_bias, grade))

    c._execute_signal = _capture_execute_signal

    c.feature_bus = FeatureBus()
    register_smc_pack(c.feature_bus)
    c.feature_bus.validate()

    published = []

    def _collect(event):
        published.append(event)

    c.arbiter = Arbiter(config.get("arbiter", {}), publish=_collect)
    c.current_open_positions = []

    return c, captured, published


def replay(df_h1, symbol, strategies, config, window=300, start=60):
    """Drive `SystemController._run_strategies` over `df_h1` H1 closes, one
    record per close evaluated from `start` to len(df_h1) inclusive.

    Iterates exactly like scripts/capture_parity_golden.py::capture_stream:
    the rolling window is capped at `window` bars (mirrors live
    MultiTimeframeStore frame-cap semantics; keeps replay O(n)), and bias is
    duplicated ONLY for recording (identical to what _run_strategies itself
    computes from the same window, via the Arbiter/FeatureBus path).

    Returns list[dict] SignalRecord: {i, time, bias, signal, price, sl, tp,
    grade, strategy, type} — a superset of the golden fixture's element
    schema (GOLDEN_FIELDS). `type` is the decision's order type
    (`decision["type"]`, e.g. "MARKET"/"LIMIT"; None on no-signal rows) —
    Plan 07 / Task 7: threaded through so scripts/research_run.py can resolve
    MARKET signals at the next bar's open instead of assuming LIMIT.
    """
    controller, captured, published = build_research_controller(strategies, config)
    controller.market_data = {symbol: _StubStore(h1_df=None)}
    store = controller.market_data[symbol]

    records = []
    for end in range(start, len(df_h1) + 1):
        win = df_h1.iloc[max(0, end - window):end].reset_index(drop=True)
        store.h1_df = win

        captured.clear()
        asyncio.run(controller._run_strategies(symbol, win, "H1"))

        bias_str = BiasEngine(win).get_bias_context()[0]
        time_val = str(win.iloc[-1]["time"])

        if captured:
            _, decision, name, _, grade = captured[-1]
            record = {
                "i": end,
                "time": time_val,
                "bias": bias_str,
                "signal": decision["signal"],
                "price": float(decision["price"]),
                "sl": float(decision["sl"]),
                "tp": float(decision["tp"]),
                "grade": grade,
                "strategy": name,
                "type": decision.get("type"),
            }
        else:
            record = {
                "i": end,
                "time": time_val,
                "bias": bias_str,
                "signal": None,
                "price": None,
                "sl": None,
                "tp": None,
                "grade": None,
                "strategy": None,
                "type": None,
            }
        records.append(record)

    return records


def load_h1_from_m5(df_m5):
    """Resample an M5 OHLCV frame (columns: time, open, high, low, close,
    tick_volume) to H1 candles, using the EXACT aggregation
    tests/backtest/backtest_engine.py::Backtester._load_and_process_data
    applies ("[GEN] Generating H1 Context Data" block): high=max, low=min,
    tick_volume=sum, open=first-of-hour, close=last-of-hour; drop empty
    hours; reset the index with the first column renamed 'time'.

    Mechanically mirrors that block rather than importing Backtester
    directly, since Backtester's resample step is fused with CSV/date-shift
    parsing (no standalone function to import) and this module's purity
    rule forbids I/O beyond the input frame. Verified byte-identical to
    bt.Backtester(...).h1_df for the same M5 data in
    tests/unit/test_kernel_replay.py.
    """
    temp_idx = df_m5.set_index("time")
    temp_idx.index = pd.to_datetime(temp_idx.index)

    resampler = temp_idx.resample("1h")
    h1_temp = resampler.agg({
        "high": "max",
        "low": "min",
        "tick_volume": "sum",
    })
    h1_temp["open"] = resampler["open"].first()
    h1_temp["close"] = resampler["close"].last()

    h1_df = h1_temp.dropna().reset_index()
    cols = list(h1_df.columns)
    cols[0] = "time"
    h1_df.columns = cols
    return h1_df
