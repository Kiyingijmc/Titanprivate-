"""Parity harness (Plan 03 / Task 1) — PRE-refactor golden signal-stream capture.

Drives the REAL `SystemController._run_strategies` over `test_data.csv`
H1 bars with a minimal controller fixture (real SilverBullet + SignalGrader,
real config), and freezes the resulting signal stream. Later refactors of
the signal path (feature bus extraction, etc.) are checked against this
fixture in tests/unit/test_signal_parity.py to prove byte-identical
behavior. Does not modify any src/ module; capture-only.

Run: .venv/bin/python scripts/capture_parity_golden.py
"""
import asyncio
import json
import os
import sys

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "backtest"))

import backtest_engine as bt  # noqa: E402

from src.core.system_controller import SystemController  # noqa: E402
from src.strategies.models.silver_bullet import SilverBullet  # noqa: E402
from src.analysis.signal_grader import SignalGrader  # noqa: E402
from src.analysis.bias_engine import BiasEngine  # noqa: E402

SYMBOL = "TESTUSD"
CONFIG_PATH = os.path.join(REPO_ROOT, "config", "config.yaml")
GOLDEN_PATH = os.path.join(REPO_ROOT, "tests", "backtest", "fixtures", "parity_golden_h1.json")

# Deterministic NY-time stub: fixed inside the SilverBullet all-hours window
# ([0, 24] per config) so the harness never depends on wall-clock or the
# real TimeNormalizer/broker offset. Format MUST match the real
# TimeNormalizer.get_current_ny_string() ("%H:%M:%S %Z" — see
# src/analysis/time_math.py:98-102) because SilverBullet parses the hour via
# int(ny_time_str.split(':')[0]); an ISO date-prefixed constant makes that
# raise ValueError and silently kills every signal (Task 1 BLOCKED finding,
# fix approved by coordinator 2026-07-12).
FIXED_NY_STRING = "10:00:00 EST"


class _StubLogger:
    """No-op logger satisfying log_event(type, module, msg, payload=...)."""

    def log_event(self, *args, **kwargs):
        pass


class _StubTimeEngine:
    def get_current_ny_string(self):
        return FIXED_NY_STRING


class _StubStore:
    """Stand-in for MultiTimeframeStore: only get_data("H1") is exercised
    by _run_strategies (for the bias context)."""

    def __init__(self, h1_df=None):
        self.h1_df = h1_df

    def get_data(self, tf):
        if tf == "H1":
            return self.h1_df
        return None


def _make_controller():
    """Build a minimal SystemController fixture (no __init__, no bridge/IO)
    wired with the REAL SilverBullet + SignalGrader from config/config.yaml,
    mirroring tests/unit/test_controller_events.py::make_controller.

    Returns (controller, captured) where `captured` is a list the stubbed
    _execute_signal appends (symbol, decision, name, htf_bias, grade) to.
    """
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    logger = _StubLogger()

    c = SystemController.__new__(SystemController)
    c.config = cfg
    c.logger = logger
    c.strategies = [SilverBullet(cfg['strategies']['silver_bullet'], logger)]
    c.signal_grader = SignalGrader(cfg)
    c.time_engine = _StubTimeEngine()
    c.market_data = {SYMBOL: _StubStore(h1_df=None)}

    captured = []

    async def _capture_execute_signal(symbol, decision, name, htf_bias, grade=""):
        captured.append((symbol, decision, name, htf_bias, grade))

    c._execute_signal = _capture_execute_signal

    try:  # post-refactor (Task 4+) the harness must exercise the BUS path,
          # pre-refactor these modules don't exist and the inline path runs.
        from src.features.feature_bus import FeatureBus
        from src.features.packs.smc_pack import register_smc_pack
        c.feature_bus = FeatureBus()
        register_smc_pack(c.feature_bus)
        c.feature_bus.validate()
    except ImportError:
        pass

    try:  # Plan 05 / Task 4: the fixture must exercise the SAME production
          # code path as the live controller -- i.e. through the Arbiter, not
          # the pre-Plan-05 direct-execute fallback (which real __init__
          # controllers no longer take). Sanctioned harness edit: the frozen
          # golden fixture itself is untouched; this only makes the replay
          # driver representative of production wiring. publish=None (no
          # tape) since this harness only cares about the executed args.
        from src.arbiter.arbiter import Arbiter
        c.arbiter = Arbiter(cfg.get('arbiter', {}), publish=None)
        c.current_open_positions = []
    except ImportError:
        pass

    return c, captured


def capture_stream(csv_path):
    """Replay test_data.csv as H1 closes through the real controller signal
    path, one record per H1 close evaluated:
        {"i": int, "bias": str, "signal": str|None,
         "price": float|None, "sl": float|None, "tp": float|None,
         "grade": str|None}
    Deterministic: no randomness, no wall-clock (time_engine is stubbed).
    """
    engine = bt.Backtester(csv_path)  # reuses the repo's CSV load + H1 resample
    h1 = engine.h1_df

    controller, captured = _make_controller()
    store = controller.market_data[SYMBOL]

    stream = []
    for end in range(60, len(h1) + 1):
        # Cap the rolling window at 300 bars: mirrors live MultiTimeframeStore
        # frame-cap semantics and keeps the parity capture O(n) instead of
        # O(n^2) (uncapped windows blew the unit suite from ~10s to 862s).
        # Coordinator-approved plan amendment; the one sanctioned pre-refactor
        # fixture regeneration.
        window = h1.iloc[max(0, end - 300):end].reset_index(drop=True)
        store.h1_df = window

        captured.clear()
        asyncio.run(controller._run_strategies(SYMBOL, window, "H1"))

        # Duplicate the bias computation ONLY for recording — identical
        # pre/post refactor since it mirrors what _run_strategies itself
        # computes from the same window.
        bias_str = BiasEngine(window).get_bias_context()[0]

        if captured:
            _, decision, _, _, grade = captured[-1]
            record = {
                "i": end,
                "bias": bias_str,
                "signal": decision["signal"],
                "price": float(decision["price"]),
                "sl": float(decision["sl"]),
                "tp": float(decision["tp"]),
                "grade": grade,
            }
        else:
            record = {
                "i": end,
                "bias": bias_str,
                "signal": None,
                "price": None,
                "sl": None,
                "tp": None,
                "grade": None,
            }
        stream.append(record)

    return stream


def main():
    stream = capture_stream("test_data.csv")
    n_signals = sum(1 for r in stream if r["signal"] is not None)

    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w") as f:
        json.dump(stream, f, indent=1)

    print(f"[GOLDEN] stream length: {len(stream)}")
    print(f"[GOLDEN] non-None signals: {n_signals}")
    print(f"[GOLDEN] wrote {GOLDEN_PATH}")


if __name__ == "__main__":
    main()
