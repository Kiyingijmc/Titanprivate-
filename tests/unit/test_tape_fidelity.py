"""Golden-tape fidelity (Plan-02 final-review advisory, Task 5):
SpecsUpdated carries broker spec values (with legacy-tape back-compat), and
_snapshot_warmup journals per-symbol/tf warmup buffers with a sha256 so a
replay can verify it was fed the same data the live run saw."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.core.bus import EventBus
from src.core.events import Event, SpecsUpdated, WarmupSnapshot
from src.core.system_controller import SystemController


def make_controller(root_dir):
    c = SystemController.__new__(SystemController)
    c.bus = EventBus()
    c.root_dir = Path(root_dir)
    c.logger = MagicMock()
    c.market_data = {}
    return c


def capture(bus, evt_cls):
    seen = []
    bus.subscribe(evt_cls, seen.append)
    return seen


class TestSpecsUpdatedBackCompat(unittest.TestCase):
    def test_legacy_dict_without_new_keys_parses_with_zero_defaults(self):
        legacy = {"evt": "SpecsUpdated", "symbol": "X"}
        evt = Event.from_dict(legacy)
        self.assertEqual(evt, SpecsUpdated(symbol="X", tick_value=0.0,
                                           tick_size=0.0, vol_min=0.0,
                                           vol_step=0.0))

    def test_specs_updated_round_trips_with_values(self):
        evt = SpecsUpdated(symbol="XAUUSD", tick_value=1.0, tick_size=0.01,
                           vol_min=0.01, vol_step=0.01)
        rt = Event.from_dict(evt.to_dict())
        self.assertEqual(rt, evt)


class TestWarmupSnapshotEvent(unittest.TestCase):
    def test_warmup_snapshot_round_trips(self):
        evt = WarmupSnapshot(symbol="EURUSD", tf="M5", n_bars=500,
                             path="data/journal/warmup/x/EURUSD_M5.csv",
                             sha256="deadbeef")
        rt = Event.from_dict(evt.to_dict())
        self.assertEqual(rt, evt)


class TestSnapshotWarmup(unittest.TestCase):
    def test_writes_csv_and_publishes_matching_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_controller(tmp)
            df = pd.DataFrame([
                {"time": "2026-07-12T10:00:00", "open": 1.0, "high": 1.1,
                 "low": 0.9, "close": 1.05},
                {"time": "2026-07-12T10:05:00", "open": 1.05, "high": 1.2,
                 "low": 1.0, "close": 1.1},
            ])
            store = MagicMock()
            store.get_data.side_effect = lambda tf: df if tf == "M5" else pd.DataFrame()
            c.market_data = {"EURUSD": store}

            seen = capture(c.bus, WarmupSnapshot)
            c._snapshot_warmup()

            self.assertEqual(len(seen), 1)
            evt = seen[0]
            self.assertEqual(evt.symbol, "EURUSD")
            self.assertEqual(evt.tf, "M5")
            self.assertEqual(evt.n_bars, 2)

            written_path = Path(evt.path)
            self.assertTrue(written_path.exists())
            recomputed = hashlib.sha256(written_path.read_bytes()).hexdigest()
            self.assertEqual(recomputed, evt.sha256)

    def test_store_that_raises_is_swallowed_no_event_no_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_controller(tmp)
            store = MagicMock()
            store.get_data.side_effect = RuntimeError("boom")
            c.market_data = {"EURUSD": store}

            seen = capture(c.bus, WarmupSnapshot)
            c._snapshot_warmup()  # must not raise

            self.assertEqual(seen, [])
            self.assertTrue(c.logger.log_event.called)


if __name__ == "__main__":
    unittest.main()
