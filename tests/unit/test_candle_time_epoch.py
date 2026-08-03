# ==============================================================================
# FILE: tests/unit/test_candle_time_epoch.py
# Covers: src/core/candle_maker.py, src/core/data_store.py
#
# Regression coverage for the naive-datetime epoch mismatch between the
# history path (DataStore.ingest_history -> naive UTC via pd.to_datetime)
# and the live-tick path (CandleMaker.process_tick -> was naive LOCAL time
# via bare datetime.fromtimestamp()). Both paths feed the same buffer
# (CandleMaker.candles), so a mismatch splices a phantom offset into the
# series at the history/live seam.
# ==============================================================================

import contextlib
import os
import time
import unittest
from datetime import datetime, timedelta, timezone

from src.core.candle_maker import CandleMaker
from src.core.data_store import MultiTimeframeStore

# Fixed epoch (seconds, UTC) used for the millisecond-parity check, where
# CandleMaker.process_tick's own bucket flooring applies symmetrically to
# both branches, so alignment doesn't matter.
EPOCH_SECONDS = 1721044213

# Bucket-aligned epoch (2024-07-15 11:50:00 UTC, on the M5 grid) used
# wherever a value is fed through DataStore.ingest_history: real MT5
# HISTORY bars already arrive pre-bucketed by the broker, and
# ingest_history does not floor its input itself.
HIST_EPOCH_SECONDS = 1721044200


def _utc_bucket(epoch_seconds, tf_min):
    """Reference conversion: broker epoch -> naive UTC, floored to the tf bucket."""
    ts = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).replace(tzinfo=None)
    minute_floored = (ts.minute // tf_min) * tf_min
    return ts.replace(minute=minute_floored, second=0, microsecond=0)


@contextlib.contextmanager
def _forced_timezone(tz_name):
    """Force the process into a non-UTC local timezone for the duration of the block.

    Without this, every case below would pass on a UTC-configured machine
    even with the pre-fix bug fully present, because naive-local and
    naive-UTC conversions coincide when the local offset is zero.
    """
    original = os.environ.get("TZ")
    os.environ["TZ"] = tz_name
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


class TestCandleTimeEpoch(unittest.TestCase):
    def test_cross_path_agreement(self):
        """History ingestion and a live tick for the same epoch must land on
        the same bucketed timestamp."""
        expected = _utc_bucket(HIST_EPOCH_SECONDS, 5)

        store = MultiTimeframeStore("EURUSD")
        store.ingest_history(
            "M5",
            [{"t": HIST_EPOCH_SECONDS, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "tv": 1}],
        )
        history_time = store.timeframes["M5"].candles.iloc[-1]["time"]

        maker = CandleMaker(5)
        maker.process_tick({"b": 1.0, "t": HIST_EPOCH_SECONDS})
        live_time = maker.current_candle["time"]

        self.assertEqual(history_time, expected)
        self.assertEqual(live_time, expected)
        self.assertEqual(history_time, live_time)

    def test_seam_contiguity(self):
        """The gap between the last history bar and the first live bar must
        be exactly one timeframe interval — not that interval plus the
        host's UTC offset."""
        tf_min = 5
        hist_bucket = _utc_bucket(EPOCH_SECONDS, tf_min)
        hist_epoch = int(hist_bucket.replace(tzinfo=timezone.utc).timestamp())

        store = MultiTimeframeStore("EURUSD")
        store.ingest_history(
            "M5", [{"t": hist_epoch, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "tv": 1}]
        )
        last_history_time = store.timeframes["M5"].candles.iloc[-1]["time"]

        # A tick 50s into the very next bucket.
        next_tick_epoch = hist_epoch + (tf_min * 60) + 50
        maker = store.timeframes["M5"]
        maker.process_tick({"b": 1.0, "t": next_tick_epoch})
        first_live_time = maker.current_candle["time"]

        gap = first_live_time - last_history_time
        self.assertEqual(gap, timedelta(minutes=tf_min))

    def test_millisecond_branch_parity(self):
        """The same instant expressed in ms vs s must produce the same
        stamped timestamp."""
        maker_seconds = CandleMaker(5)
        maker_seconds.process_tick({"b": 1.0, "t": EPOCH_SECONDS})

        maker_millis = CandleMaker(5)
        maker_millis.process_tick({"b": 1.0, "t": EPOCH_SECONDS * 1000})

        self.assertEqual(
            maker_seconds.current_candle["time"], maker_millis.current_candle["time"]
        )

    def test_timezone_independence(self):
        """Forcing a non-UTC host timezone (Africa/Kampala, UTC+3) must not
        change any of the results above. On a UTC-configured machine this
        case degenerates to a no-op (local == UTC), which is exactly why
        the other cases alone are not sufficient evidence: they can pass
        with the bug present if run on a UTC box. Forcing EAT here is what
        makes the coverage bite regardless of host timezone.
        """
        with _forced_timezone("Africa/Kampala"):
            expected = _utc_bucket(HIST_EPOCH_SECONDS, 5)

            store = MultiTimeframeStore("EURUSD")
            store.ingest_history(
                "M5",
                [{"t": HIST_EPOCH_SECONDS, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "tv": 1}],
            )
            history_time = store.timeframes["M5"].candles.iloc[-1]["time"]

            maker = CandleMaker(5)
            maker.process_tick({"b": 1.0, "t": HIST_EPOCH_SECONDS})
            live_time = maker.current_candle["time"]

            maker_millis = CandleMaker(5)
            maker_millis.process_tick({"b": 1.0, "t": EPOCH_SECONDS * 1000})
            live_time_ms = maker_millis.current_candle["time"]

            self.assertEqual(history_time, expected)
            self.assertEqual(live_time, expected)
            self.assertEqual(live_time_ms, expected)


if __name__ == "__main__":
    unittest.main()
