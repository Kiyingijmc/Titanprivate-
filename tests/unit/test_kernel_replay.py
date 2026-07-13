# tests/unit/test_kernel_replay.py
# Plan 06 / Task 3: the Kernel Replay Router — the research <-> live parity
# seam. The centerpiece test (test_replay_reproduces_golden_fixture) proves
# the generalized research driver reproduces the frozen golden fixture
# (tests/backtest/fixtures/parity_golden_h1.json) element-for-element when
# fed the real SilverBullet strategy off real config/config.yaml — i.e. the
# research path IS the live path.
import json
import os
import sys
import unittest
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "backtest"))

import backtest_engine as bt  # noqa: E402

from src.strategies.models.silver_bullet import SilverBullet  # noqa: E402
from src.research.kernel_replay import (  # noqa: E402
    build_research_controller,
    replay,
    load_h1_from_m5,
    GOLDEN_FIELDS,
)

CONFIG_PATH = os.path.join(REPO_ROOT, "config", "config.yaml")
GOLDEN_PATH = Path(REPO_ROOT) / "tests" / "backtest" / "fixtures" / "parity_golden_h1.json"
SYMBOL = "TESTUSD"


class _NullLogger:
    def log_event(self, *args, **kwargs):
        pass


class _FakeStrat:
    """A research-status strategy injected directly (no promote-gate/registry
    involvement) — proves offline activation runs through the same path."""

    name = "FakeStrat"
    timeframe = "H1"

    def __init__(self):
        self.active = True

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, window, context=None):
        # Deterministic, always-BUY decision (values that clear the >=1.5R
        # RR floor so a lenient grade config doesn't matter either way).
        return {"signal": "BUY", "type": "MARKET", "price": 1.1000, "sl": 1.0900, "tp": 1.1200}


def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _golden_h1():
    engine = bt.Backtester("test_data.csv")
    return engine, engine.h1_df


class TestReplayReproducesGolden(unittest.TestCase):
    """THE ACCEPTANCE TEST (this plan's centerpiece)."""

    def test_replay_reproduces_golden_fixture(self):
        cfg = _load_config()
        sb = SilverBullet(cfg["strategies"]["silver_bullet"], _NullLogger())

        _, h1 = _golden_h1()
        records = replay(h1, SYMBOL, [sb], cfg, window=300, start=60)

        golden = json.loads(GOLDEN_PATH.read_text())
        self.assertEqual(len(records), len(golden))

        projected = [{k: r[k] for k in GOLDEN_FIELDS} for r in records]
        for i, (got, want) in enumerate(zip(projected, golden)):
            self.assertEqual(got, want, f"divergence at element {i}")

        # Sanity: the fixture is documented as 743 elements / 13 signals.
        n_signals = sum(1 for r in golden if r["signal"] is not None)
        self.assertEqual(len(golden), 743)
        self.assertEqual(n_signals, 13)


class TestOfflineStrategyActivation(unittest.TestCase):
    """A research-status FakeStrat runs through replay: instances injected
    directly, no promote-gate/registry involvement."""

    def _cfg(self):
        return {
            "arbiter": {"thesis_ttl_bars": 0, "max_positions_per_symbol": 1,
                        "max_total_positions": 999},
            "signal_grading": {"enabled": False, "min_grade": "C"},
        }

    def test_fakestrat_produces_signals_through_replay(self):
        _, h1 = _golden_h1()
        records = replay(h1, SYMBOL, [_FakeStrat()], self._cfg(), window=300, start=60)

        self.assertEqual(len(records), len(h1) + 1 - 60)
        signals = [r for r in records if r["signal"] is not None]
        # bias filtering (BULLISH/BEARISH vs BUY) means not every bar
        # signals, but at least some must (BUY is compatible with
        # NEUTRAL/BULLISH bias) -- proves the offline strategy actually ran.
        self.assertGreater(len(signals), 0)
        for r in signals:
            self.assertEqual(r["strategy"], "FakeStrat")
            self.assertEqual(r["signal"], "BUY")

    def test_arbiter_genuinely_on_path_intent_emitted_matches_signals(self):
        # Lenient config (no thesis dedup, no caps) so every Arbiter submit
        # is guaranteed approved -> IntentEmitted count == executed-signal
        # count, proving the Arbiter -- not a bypass -- produced the stream.
        controller, captured, published = build_research_controller(
            [_FakeStrat()], self._cfg()
        )
        controller.market_data = {SYMBOL: None}  # replaced by replay()

        _, h1 = _golden_h1()

        # Re-run replay using the SAME kernel-building contract (own call,
        # since replay() builds its own controller internally).
        records = replay(h1, SYMBOL, [_FakeStrat()], self._cfg(), window=300, start=60)
        n_signals = sum(1 for r in records if r["signal"] is not None)

        # Independently drive the arbiter path the way replay() does, but
        # capture published events directly, to assert the IntentEmitted
        # count lines up with the number of executed signals.
        from src.research.kernel_replay import _StubStore
        import asyncio as _asyncio

        ctrl2, captured2, published2 = build_research_controller([_FakeStrat()], self._cfg())
        ctrl2.market_data = {SYMBOL: _StubStore(h1_df=None)}
        store2 = ctrl2.market_data[SYMBOL]
        n_signals2 = 0
        for end in range(60, len(h1) + 1):
            win = h1.iloc[max(0, end - 300):end].reset_index(drop=True)
            store2.h1_df = win
            captured2.clear()
            _asyncio.run(ctrl2._run_strategies(SYMBOL, win, "H1"))
            if captured2:
                n_signals2 += 1

        intent_emitted = [e for e in published2 if type(e).__name__ == "IntentEmitted"]
        self.assertEqual(len(intent_emitted), n_signals2)
        self.assertEqual(n_signals2, n_signals)
        self.assertGreater(n_signals, 0)


class TestWindowStartParameters(unittest.TestCase):
    def test_shorter_run_has_fewer_records_and_correct_offsets(self):
        cfg = _load_config()
        sb = SilverBullet(cfg["strategies"]["silver_bullet"], _NullLogger())
        _, h1 = _golden_h1()

        full = replay(h1, SYMBOL, [sb], cfg, window=300, start=60)
        short = replay(h1, SYMBOL, [sb], cfg, window=300, start=200)

        self.assertLess(len(short), len(full))
        self.assertEqual(len(short), len(h1) + 1 - 200)
        self.assertEqual(short[0]["i"], 200)
        self.assertEqual(short[-1]["i"], len(h1))
        self.assertEqual(full[0]["i"], 60)
        self.assertEqual(full[-1]["i"], len(h1))

        # Overlapping tail (same i's) must agree element-for-element: window
        # cap means the state each i sees is identical regardless of start.
        offset = 200 - 60
        for a, b in zip(full[offset:], short):
            self.assertEqual(a["i"], b["i"])
            self.assertEqual(a["bias"], b["bias"])
            self.assertEqual(a["signal"], b["signal"])


class TestLoadH1FromM5(unittest.TestCase):
    def test_matches_backtest_engine_resample(self):
        engine, want = _golden_h1()
        got = load_h1_from_m5(engine.m5_df)
        pd.testing.assert_frame_equal(
            got.reset_index(drop=True), want.reset_index(drop=True)
        )


if __name__ == "__main__":
    unittest.main()
