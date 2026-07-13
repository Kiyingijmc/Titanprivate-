# tests/unit/test_research_run.py
# Plan 06 / Task 4: scripts/research_run.py -- the research_run CLI.
#
# End-to-end over test_data.csv with silver_bullet, driven through
# scripts/research_run.py::main(argv) directly (no subprocess). Every run is
# pointed at a tempdir via --out so tests never write into data/results.
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))

import backtest_engine as bt  # noqa: E402

from research_run import main as research_main  # noqa: E402

TEST_DATA_CSV = os.path.join(REPO, "test_data.csv")

# tests/backtest/fixtures/parity_golden_h1.json is documented (and pinned by
# test_signal_parity.py / test_kernel_replay.py) as 743 elements / 13 signals
# for test_data.csv + silver_bullet off config/config.yaml.
GOLDEN_N_SIGNALS = 13


class _ResearchRunTestBase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="titan_research_run_test_")
        self.out_dir = Path(self._tmpdir) / "results"

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run(self, argv, expect_ok=True):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = research_main(argv)
        if expect_ok:
            self.assertEqual(rc, 0, out.getvalue())
        return rc, out.getvalue()

    def _base_argv(self, **overrides):
        argv = {
            "--csv": TEST_DATA_CSV, "--symbol": "BTCUSD", "--tf": "H1",
            "--strategy": "silver_bullet", "--out": str(self.out_dir),
        }
        argv.update(overrides)
        flat = []
        for k, v in argv.items():
            flat += [k, str(v)]
        return flat

    def _only_run_dir(self):
        entries = list(self.out_dir.iterdir())
        self.assertEqual(len(entries), 1, f"expected exactly one run dir, got {entries}")
        return entries[0]

    def _read_jsonl(self, path):
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]


class TestEndToEndRun(_ResearchRunTestBase):
    def test_run_creates_card_with_full_schema_and_pins_signal_count(self):
        rc, output = self._run(self._base_argv())
        self.assertEqual(rc, 0)

        run_dir = self._only_run_dir()
        self.assertTrue((run_dir / "run.json").exists())
        self.assertTrue((run_dir / "signals.jsonl").exists())

        card = json.loads((run_dir / "run.json").read_text())

        # Run-card schema (Plan 06 Task 4 spec).
        self.assertIn("git_sha", card)
        self.assertIn("strategy", card)
        self.assertEqual(card["strategy"]["id"], "silver_bullet")
        self.assertTrue(card["strategy"]["version"])
        self.assertIn("config_hash", card)
        self.assertEqual(len(card["config_hash"]), 64)  # sha256 hex digest
        self.assertIn("data", card)
        self.assertEqual(card["data"]["source"], TEST_DATA_CSV)
        self.assertEqual(len(card["data"]["sha256"]), 64)
        self.assertIn("n_bars", card)
        self.assertIn("n_signals", card)
        self.assertIn("n_trades", card)
        self.assertIn("metrics", card)
        self.assertIn("is", card["metrics"])
        self.assertIn("oos", card["metrics"])
        self.assertIn("spread_assumption", card)
        self.assertIn("timestamp", card)

        # Consistency pin: n_signals must match the frozen golden fixture.
        self.assertEqual(card["n_signals"], GOLDEN_N_SIGNALS)

        # aggregate_metrics' actual return shape (backtest_engine.py) -- not
        # the plan's shorthand n/exp/totR names.
        for split_name in ("is", "oos"):
            m = card["metrics"][split_name]
            for key in ("trades", "expectancy", "total_r", "win_rate",
                        "profit_factor", "max_drawdown_r"):
                self.assertIn(key, m)

        # signals.jsonl has exactly one line per executed signal.
        signals = self._read_jsonl(run_dir / "signals.jsonl")
        self.assertEqual(len(signals), GOLDEN_N_SIGNALS)

        # Printed report names the cost model actually used.
        self.assertIn("cost_model=trade_dollars", output)


class TestSplitRespected(_ResearchRunTestBase):
    def test_split_respected_is_and_oos_counts_sum(self):
        rc, _ = self._run(self._base_argv(**{"--split": "0.6"}))
        self.assertEqual(rc, 0)

        run_dir = self._only_run_dir()
        card = json.loads((run_dir / "run.json").read_text())
        signals = self._read_jsonl(run_dir / "signals.jsonl")

        self.assertEqual(card["split"], 0.6)

        is_trades, oos_trades = bt.split_trades(signals, train_frac=0.6)
        self.assertEqual(len(is_trades) + len(oos_trades), len(signals))

        want_is = bt.aggregate_metrics(is_trades)
        want_oos = bt.aggregate_metrics(oos_trades)
        self.assertEqual(card["metrics"]["is"]["trades"], want_is["trades"])
        self.assertEqual(card["metrics"]["oos"]["trades"], want_oos["trades"])

        # split_trades is a strict partition, and aggregate_metrics' TP/SL
        # filter doesn't care which half a trade lands in -- so resolved
        # (TP/SL) counts across IS+OOS must equal the resolved count over
        # the whole (unsplit) trade list, even though some signals never
        # resolve to TP/SL (EXPIRED/OPEN_AT_END/INVALID), so this need not
        # equal len(signals).
        want_all = bt.aggregate_metrics(signals)
        self.assertGreater(want_all["trades"], 0)
        self.assertEqual(
            card["metrics"]["is"]["trades"] + card["metrics"]["oos"]["trades"],
            want_all["trades"],
        )


class TestUnknownStrategyCleanError(_ResearchRunTestBase):
    def test_unknown_strategy_id_reports_clean_error(self):
        rc, output = self._run(
            self._base_argv(**{"--strategy": "does_not_exist"}), expect_ok=False,
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown strategy id", output)
        self.assertNotIn("Traceback", output)
        self.assertFalse(self.out_dir.exists())


class TestSpreadFlowsIntoNetR(_ResearchRunTestBase):
    def test_different_spreads_produce_different_expectancy(self):
        rc1, _ = self._run(self._base_argv(**{
            "--spread-pips": "5", "--out": str(self.out_dir / "cheap"),
        }))
        rc2, _ = self._run(self._base_argv(**{
            "--spread-pips": "500", "--out": str(self.out_dir / "expensive"),
        }))
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)

        cheap_dirs = list((self.out_dir / "cheap").iterdir())
        expensive_dirs = list((self.out_dir / "expensive").iterdir())
        self.assertEqual(len(cheap_dirs), 1)
        self.assertEqual(len(expensive_dirs), 1)

        cheap_card = json.loads((cheap_dirs[0] / "run.json").read_text())
        expensive_card = json.loads((expensive_dirs[0] / "run.json").read_text())

        self.assertGreater(cheap_card["n_signals"], 0)
        self.assertNotEqual(
            cheap_card["metrics"]["is"]["expectancy"],
            expensive_card["metrics"]["is"]["expectancy"],
        )
        # Higher spread must never produce a *better* expectancy.
        self.assertGreaterEqual(
            cheap_card["metrics"]["is"]["expectancy"],
            expensive_card["metrics"]["is"]["expectancy"],
        )


class TestTimeframeRestrictionH1Only(_ResearchRunTestBase):
    def test_non_h1_timeframe_rejected_at_argparse(self):
        """Verify that --tf M5 (or other non-H1 values) fails cleanly with argparse
        SystemExit code 2 and does not create a run directory."""
        stderr_capture = io.StringIO()
        with contextlib.redirect_stderr(stderr_capture):
            with self.assertRaises(SystemExit) as ctx:
                research_main(self._base_argv(**{"--tf": "M5"}))

        self.assertEqual(ctx.exception.code, 2,
                         "argparse should exit with code 2 for invalid choice")
        # Verify no run directory was created (out_dir should not exist)
        self.assertFalse(self.out_dir.exists(),
                         "no run directory should be created when argparse fails")


if __name__ == "__main__":
    unittest.main()
