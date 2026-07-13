"""Unit tests for scripts/lake_import.py and scripts/lake_prune.py.

Covers: MT5 tab-export parsing, comma/datetime CSV parsing, filename ->
symbol/tf inference, --all-history continue-on-error aggregation, and
prune CLI dry-run vs --execute against a tmp lake.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import pandas as pd  # noqa: E402

from src.data.lake import Lake  # noqa: E402
from lake_import import main as import_main, sniff_and_read, infer_symbol_tf  # noqa: E402
from lake_prune import main as prune_main  # noqa: E402


TAB_CSV = (
    "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
    "2025.12.01\t00:00:00\t91146.19\t91240.69\t91146.14\t91236.27\t560\t0\t2490\n"
    "2025.12.01\t00:05:00\t91236.19\t91289.43\t91213.40\t91255.85\t507\t0\t2490\n"
)

COMMA_CSV = (
    "datetime,open,high,low,close\n"
    "2023-06-26 00:05:00,1.09008,1.09008,1.09005,1.09005\n"
    "2023-06-26 00:10:00,1.09005,1.09005,1.08998,1.08998\n"
)

CORRUPT_CSV = (
    "datetime,open,high,low,close\n"
    "2023-06-26 00:05:00,not-a-number,1.09008,1.09005,1.09005\n"
)


class LakeImportTestBase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="titan_lake_import_test_")
        self.lake_root = Path(self._tmpdir) / "lake"

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = Path(self._tmpdir) / name
        path.write_text(content)
        return path


class TestSniffAndRead(LakeImportTestBase):
    def test_tab_format_parses_to_normalized_frame(self):
        path = self._write("mt5_export.csv", TAB_CSV)
        df = sniff_and_read(path)

        self.assertListEqual(list(df.columns[:5]), ["time", "open", "high", "low", "close"])
        self.assertEqual(len(df), 2)
        self.assertEqual(pd.Timestamp(df["time"].iloc[0]), pd.Timestamp("2025-12-01 00:00:00"))
        self.assertAlmostEqual(df["open"].iloc[0], 91146.19)
        self.assertAlmostEqual(df["close"].iloc[1], 91255.85)
        self.assertIn("volume", df.columns)
        self.assertEqual(df["volume"].iloc[0], 560)

    def test_comma_datetime_format_parses_to_normalized_frame(self):
        path = self._write("EURUSD_M5.csv", COMMA_CSV)
        df = sniff_and_read(path)

        self.assertListEqual(list(df.columns), ["time", "open", "high", "low", "close"])
        self.assertEqual(len(df), 2)
        self.assertEqual(pd.Timestamp(df["time"].iloc[0]), pd.Timestamp("2023-06-26 00:05:00"))
        self.assertAlmostEqual(df["close"].iloc[1], 1.08998)


class TestFilenameInference(unittest.TestCase):
    def test_infers_symbol_and_tf(self):
        self.assertEqual(infer_symbol_tf(Path("EURUSD_M5.csv")), ("EURUSD", "M5"))
        self.assertEqual(infer_symbol_tf(Path("XAUUSD_D1.csv")), ("XAUUSD", "D1"))

    def test_returns_none_for_unrecognized_filename(self):
        self.assertIsNone(infer_symbol_tf(Path("EURUSD_report.txt")))
        self.assertIsNone(infer_symbol_tf(Path("EURUSD_trades.csv")))


class TestImportMainSingleFile(LakeImportTestBase):
    def test_ingests_comma_csv_via_cli(self):
        path = self._write("EURUSD_M5.csv", COMMA_CSV)
        rc = import_main([
            "--csv", str(path),
            "--symbol", "EURUSD",
            "--tf", "M5",
            "--lake-root", str(self.lake_root),
        ])
        self.assertEqual(rc, 0)

        lake = Lake(self.lake_root)
        loaded = lake.load("EURUSD", "M5", broker="fbs")
        self.assertEqual(len(loaded), 2)


class TestAllHistoryContinueOnError(LakeImportTestBase):
    def test_good_file_ingested_corrupt_file_skipped_summary_counts(self):
        hist_dir = Path(self._tmpdir) / "history"
        hist_dir.mkdir()
        (hist_dir / "EURUSD_M5.csv").write_text(COMMA_CSV)
        (hist_dir / "GBPUSD_M5.csv").write_text(CORRUPT_CSV)

        rc = import_main([
            "--all-history",
            "--history-dir", str(hist_dir),
            "--lake-root", str(self.lake_root),
        ])
        self.assertEqual(rc, 0)  # at least one file ok -> exit 0

        lake = Lake(self.lake_root)
        loaded = lake.load("EURUSD", "M5", broker="fbs")
        self.assertEqual(len(loaded), 2)
        with self.assertRaises(Exception):
            lake.load("GBPUSD", "M5", broker="fbs")

    def test_exit_code_1_when_no_files_ok(self):
        hist_dir = Path(self._tmpdir) / "history"
        hist_dir.mkdir()
        (hist_dir / "GBPUSD_M5.csv").write_text(CORRUPT_CSV)

        rc = import_main([
            "--all-history",
            "--history-dir", str(hist_dir),
            "--lake-root", str(self.lake_root),
        ])
        self.assertEqual(rc, 1)


class TestPruneCli(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="titan_lake_prune_cli_test_")
        self.lake_root = Path(self._tmpdir) / "lake"
        self.lake = Lake(self.lake_root)

        from datetime import datetime, timedelta, timezone
        df = pd.DataFrame({
            "time": pd.date_range("2018-01-01", periods=5, freq="5min"),
            "open": [1.0] * 5, "high": [1.1] * 5, "low": [0.9] * 5, "close": [1.0] * 5,
        })
        self.lake.ingest(df, broker="fbs", symbol="EURUSD", tf="M5", source="test")

        manifest = self.lake.manifest()
        stale_iso = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        manifest["fbs"]["EURUSD"]["M5"]["2018"]["last_used"] = stale_iso
        self.lake._write_manifest(manifest)

        self.partition_path = self.lake_root / "fbs" / "EURUSD" / "M5" / "2018.parquet"

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_dry_run_does_not_delete(self):
        rc = prune_main(["--lake-root", str(self.lake_root)])
        self.assertEqual(rc, 0)
        self.assertTrue(self.partition_path.exists())

    def test_execute_deletes(self):
        rc = prune_main(["--lake-root", str(self.lake_root), "--execute"])
        self.assertEqual(rc, 0)
        self.assertFalse(self.partition_path.exists())


if __name__ == "__main__":
    unittest.main()
