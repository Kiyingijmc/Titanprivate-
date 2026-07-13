"""Unit tests for src.data.lake.Lake — parquet research lake.

Covers: ingest/load round-trip, year partitioning, merge-dedupe on
re-ingest, validation-on-ingest (+ quarantine), load span filtering,
last_used touch, and prune (dry-run + real, frozen/ exclusion).
"""
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.data.lake import Lake, LakeError


def _bars(start, periods, freq="5min", base=1.1000):
    """Deterministic, valid OHLC frame."""
    times = pd.date_range(start=start, periods=periods, freq=freq)
    rows = []
    for i, t in enumerate(times):
        o = base + i * 0.0001
        c = o + 0.00005
        h = max(o, c) + 0.00002
        l = min(o, c) - 0.00002
        rows.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 100 + i})
    return pd.DataFrame(rows)


class LakeTestBase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="titan_lake_test_")
        self.root = Path(self._tmpdir) / "lake"
        self.lake = Lake(self.root)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestIngestLoadRoundTrip(LakeTestBase):
    def test_round_trip_values_dtypes_sorted(self):
        df = _bars("2024-01-01", 10)
        # shuffle before ingest to prove ingest sorts
        shuffled = df.sample(frac=1, random_state=7).reset_index(drop=True)

        self.lake.ingest(shuffled, broker="fbs", symbol="EURUSD", tf="M5", source="test")
        loaded = self.lake.load("EURUSD", "M5", broker="fbs")

        expected = df.sort_values("time").reset_index(drop=True)
        self.assertTrue(loaded["time"].is_monotonic_increasing)
        self.assertEqual(len(loaded), len(expected))
        pd.testing.assert_series_equal(
            loaded["time"].reset_index(drop=True),
            pd.to_datetime(expected["time"]).reset_index(drop=True),
            check_names=False,
        )
        for col in ("open", "high", "low", "close", "volume"):
            pd.testing.assert_series_equal(
                loaded[col].reset_index(drop=True),
                expected[col].reset_index(drop=True),
                check_names=False,
            )


class TestYearPartitioning(LakeTestBase):
    def test_span_two_years_writes_two_files(self):
        df1 = _bars("2023-06-01", 5, freq="30min")
        df2 = _bars("2024-06-01", 5, freq="30min", base=1.2000)
        df = pd.concat([df1, df2], ignore_index=True)

        written = self.lake.ingest(df, broker="fbs", symbol="XAUUSD", tf="M30", source="test")

        self.assertEqual(len(written), 2)
        pdir = self.root / "fbs" / "XAUUSD" / "M30"
        self.assertTrue((pdir / "2023.parquet").exists())
        self.assertTrue((pdir / "2024.parquet").exists())

        manifest = self.lake.manifest()
        years = manifest["fbs"]["XAUUSD"]["M30"]
        self.assertEqual(set(years.keys()), {"2023", "2024"})
        self.assertEqual(years["2023"]["rows"], 5)
        self.assertEqual(years["2024"]["rows"], 5)


class TestMergeDedupe(LakeTestBase):
    def test_overlapping_reingest_no_duplicate_timestamps(self):
        first = _bars("2024-06-01", 10)
        self.lake.ingest(first, broker="fbs", symbol="EURUSD", tf="M5", source="first")

        manifest_before = self.lake.manifest()
        sha_before = manifest_before["fbs"]["EURUSD"]["M5"]["2024"]["sha256"]

        # overlap: last 5 rows of `first` plus 5 new rows, with changed close
        # on the overlapping timestamps to prove "last write wins" merge.
        overlap = first.iloc[5:].copy()
        overlap["close"] = overlap["close"] + 0.001
        overlap["high"] = overlap[["open", "close"]].max(axis=1) + 0.00002
        extra = _bars("2024-06-01 01:00", 5, base=1.5000)
        second = pd.concat([overlap, extra], ignore_index=True)

        self.lake.ingest(second, broker="fbs", symbol="EURUSD", tf="M5", source="second")

        loaded = self.lake.load("EURUSD", "M5", broker="fbs")
        self.assertEqual(len(loaded), 15)  # 10 + 5 new, 5 overlap deduped
        self.assertFalse(loaded["time"].duplicated().any())
        self.assertTrue(loaded["time"].is_monotonic_increasing)

        # last-write-wins: overlapping timestamps should carry the updated close
        merged_overlap_rows = loaded[loaded["time"].isin(overlap["time"])]
        self.assertTrue((merged_overlap_rows["close"].values == overlap["close"].values).all())

        manifest_after = self.lake.manifest()
        entry = manifest_after["fbs"]["EURUSD"]["M5"]["2024"]
        self.assertEqual(entry["rows"], 15)
        self.assertNotEqual(entry["sha256"], sha_before)


class TestValidationOnIngest(LakeTestBase):
    def _rejected_files(self):
        qdir = self.root / ".rejected"
        return sorted(qdir.glob("*")) if qdir.exists() else []

    def test_validation_failures_raise_and_quarantine(self):
        cases = {}

        missing_col = _bars("2024-01-01", 5).drop(columns=["close"])
        cases["missing_required_column"] = missing_col

        bad_time = _bars("2024-01-01", 5)
        bad_time["time"] = bad_time["time"].astype(object)
        bad_time.loc[2, "time"] = "not-a-timestamp"
        cases["unparseable_time"] = bad_time

        nan_ohlc = _bars("2024-01-01", 5)
        nan_ohlc.loc[1, "close"] = float("nan")
        cases["nan_in_ohlc"] = nan_ohlc

        bad_high_low = _bars("2024-01-01", 5)
        bad_high_low.loc[0, "high"] = bad_high_low.loc[0, "low"] - 0.01
        cases["high_less_than_low"] = bad_high_low

        bad_high_open = _bars("2024-01-01", 5)
        bad_high_open.loc[0, "high"] = bad_high_open.loc[0, "open"] - 0.01
        cases["high_less_than_open"] = bad_high_open

        bad_low_close = _bars("2024-01-01", 5)
        bad_low_close.loc[0, "low"] = bad_low_close.loc[0, "close"] + 0.01
        cases["low_greater_than_close"] = bad_low_close

        for label, bad_df in cases.items():
            with self.subTest(case=label):
                before = set(self._rejected_files())
                with self.assertRaises(LakeError):
                    self.lake.ingest(bad_df, broker="fbs", symbol="EURUSD", tf="M5", source="bad")
                after = set(self._rejected_files())
                new_files = after - before
                self.assertEqual(len(new_files), 2, "expected a quarantine csv + reason file")
                reason_files = [f for f in new_files if f.name.endswith(".reason.txt")]
                self.assertEqual(len(reason_files), 1)
                self.assertGreater(reason_files[0].stat().st_size, 0)

    def test_string_ohlc_impossible_candle_rejected(self):
        # Reviewer repro: string-typed OHLC where numerically high < low.
        # Lexicographically "9" > "10", so without numeric coercion the
        # geometry checks pass and a broken candle lands in parquet as str.
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=1, freq="5min"),
                "open": ["9"],
                "high": ["9"],
                "low": ["10"],
                "close": ["9"],
            }
        )
        before = set(self._rejected_files())
        with self.assertRaises(LakeError):
            self.lake.ingest(df, broker="fbs", symbol="EURUSD", tf="M5", source="bad")
        new_files = set(self._rejected_files()) - before
        self.assertEqual(len(new_files), 2, "expected a quarantine csv + reason file")

    def test_non_numeric_ohlc_token_rejected(self):
        df = _bars("2024-01-01", 5)
        df["close"] = df["close"].astype(object)
        df.loc[2, "close"] = "abc"
        before = set(self._rejected_files())
        with self.assertRaises(LakeError):
            self.lake.ingest(df, broker="fbs", symbol="EURUSD", tf="M5", source="bad")
        new_files = set(self._rejected_files()) - before
        self.assertEqual(len(new_files), 2, "expected a quarantine csv + reason file")

    def test_numeric_strings_coerced_and_written_numeric(self):
        df = _bars("2024-01-01", 5)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].map(lambda v: f"{v:.5f}")  # all-string numerics

        self.lake.ingest(df, broker="fbs", symbol="EURUSD", tf="M5", source="strs")
        loaded = self.lake.load("EURUSD", "M5", broker="fbs")

        for col in ("open", "high", "low", "close"):
            self.assertTrue(
                pd.api.types.is_float_dtype(loaded[col]),
                f"{col} should load as float dtype, got {loaded[col].dtype}",
            )
        self.assertAlmostEqual(loaded["open"].iloc[0], 1.1000, places=5)

    def test_duplicate_timestamps_after_dedupe_still_strictly_increasing(self):
        # sanity: identical timestamps in a single ingest batch collapse via
        # dedupe (keep-last) rather than raising, since post-dedupe the
        # series is strictly increasing.
        df = _bars("2024-01-01", 3)
        dup_row = df.iloc[[0]].copy()
        dup_row["close"] = dup_row["close"] + 0.01
        dup_row["high"] = dup_row[["open", "close"]].max(axis=1) + 0.00002
        df_with_dup = pd.concat([df, dup_row], ignore_index=True)

        self.lake.ingest(df_with_dup, broker="fbs", symbol="EURUSD", tf="M5", source="dup")
        loaded = self.lake.load("EURUSD", "M5", broker="fbs")
        self.assertEqual(len(loaded), 3)
        self.assertFalse(loaded["time"].duplicated().any())


class TestLoadFiltering(LakeTestBase):
    def test_start_end_filtering(self):
        df = _bars("2024-03-01", 20, freq="1h")
        self.lake.ingest(df, broker="fbs", symbol="GBPUSD", tf="H1", source="test")

        start = df["time"].iloc[5]
        end = df["time"].iloc[14]
        loaded = self.lake.load("GBPUSD", "H1", broker="fbs", start=start, end=end)

        self.assertEqual(len(loaded), 10)
        self.assertTrue((loaded["time"] >= start).all())
        self.assertTrue((loaded["time"] <= end).all())

    def test_missing_partition_raises_naming_existing(self):
        df = _bars("2024-01-01", 5)
        self.lake.ingest(df, broker="fbs", symbol="EURUSD", tf="M5", source="test")

        with self.assertRaises(LakeError) as ctx:
            self.lake.load("GBPUSD", "M5", broker="fbs")
        self.assertIn("EURUSD", str(ctx.exception))


class TestLoadTouchesLastUsed(LakeTestBase):
    def test_load_updates_last_used(self):
        df = _bars("2024-01-01", 5)
        self.lake.ingest(df, broker="fbs", symbol="EURUSD", tf="M5", source="test")

        before = self.lake.manifest()["fbs"]["EURUSD"]["M5"]["2024"]["last_used"]
        created = self.lake.manifest()["fbs"]["EURUSD"]["M5"]["2024"]["created"]

        import time as _time
        _time.sleep(0.01)
        self.lake.load("EURUSD", "M5", broker="fbs")

        after = self.lake.manifest()["fbs"]["EURUSD"]["M5"]["2024"]["last_used"]
        after_created = self.lake.manifest()["fbs"]["EURUSD"]["M5"]["2024"]["created"]

        self.assertNotEqual(before, after)
        self.assertEqual(created, after_created)  # created is immutable


class TestPrune(LakeTestBase):
    def _seed(self, now):
        # Old + unused (prune-eligible): 2018 data, last used long ago.
        old_df = _bars("2018-01-01", 5)
        self.lake.ingest(old_df, broker="fbs", symbol="EURUSD", tf="M5", source="old")

        # Old year but recently used -> not eligible (unused_days not met).
        recent_use_df = _bars("2018-06-01", 5)
        self.lake.ingest(recent_use_df, broker="fbs", symbol="GBPUSD", tf="M5", source="old2")
        self.lake.load("GBPUSD", "M5", broker="fbs")  # touches last_used to "now"

        # Recent year, old last_used -> not eligible (active_years not met).
        recent_df = _bars(f"{now.year}-01-02", 5)
        self.lake.ingest(recent_df, broker="fbs", symbol="USDJPY", tf="M5", source="recent")

        # Frozen: old + unused but under frozen/ -> must never be touched.
        frozen_df = _bars("2018-01-01", 5)
        self.lake.ingest(frozen_df, broker="frozen", symbol="EURUSD", tf="M5", source="frozen")

        # Backdate last_used for the "old+unused" and "frozen" entries so
        # they read as stale without waiting for real time to pass.
        manifest = self.lake.manifest()
        stale_iso = (now - timedelta(days=400)).isoformat()
        manifest["fbs"]["EURUSD"]["M5"]["2018"]["last_used"] = stale_iso
        manifest["frozen"]["EURUSD"]["M5"]["2018"]["last_used"] = stale_iso
        self.lake._write_manifest(manifest)

    def test_dry_run_lists_only_eligible_and_never_frozen(self):
        now = datetime.now(timezone.utc)
        self._seed(now)

        candidates = self.lake.prune(active_years=4, unused_days=180, now=now, dry_run=True)

        self.assertEqual(len(candidates), 1)
        self.assertIn("EURUSD", candidates[0])
        self.assertIn("fbs", candidates[0])
        self.assertNotIn("frozen", candidates[0])

        # dry-run must not delete anything.
        self.assertTrue((self.root / "fbs" / "EURUSD" / "M5" / "2018.parquet").exists())
        self.assertTrue((self.root / "frozen" / "EURUSD" / "M5" / "2018.parquet").exists())

    def test_real_run_deletes_and_updates_manifest(self):
        now = datetime.now(timezone.utc)
        self._seed(now)

        deleted = self.lake.prune(active_years=4, unused_days=180, now=now, dry_run=False)

        self.assertEqual(len(deleted), 1)
        self.assertFalse((self.root / "fbs" / "EURUSD" / "M5" / "2018.parquet").exists())
        # frozen partition and its file must survive untouched.
        self.assertTrue((self.root / "frozen" / "EURUSD" / "M5" / "2018.parquet").exists())

        manifest = self.lake.manifest()
        self.assertNotIn("2018", manifest.get("fbs", {}).get("EURUSD", {}).get("M5", {}))
        self.assertIn("2018", manifest["frozen"]["EURUSD"]["M5"])
        # the untouched candidates remain in the manifest too.
        self.assertIn("2018", manifest["fbs"]["GBPUSD"]["M5"])
        self.assertIn(str(now.year), manifest["fbs"]["USDJPY"]["M5"])


if __name__ == "__main__":
    unittest.main()
