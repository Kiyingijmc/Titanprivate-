import csv
import os, sys, tempfile, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from src.core.state_manager import StateManager  # noqa: E402
from export_journal import export_journal  # noqa: E402


class JournalExport(unittest.TestCase):
    def test_exports_closed_trades_with_full_record(self):
        tmp = tempfile.TemporaryDirectory()
        db = os.path.join(tmp.name, "state.db")
        out = os.path.join(tmp.name, "journal.csv")

        sm = StateManager(db)
        sm.register_order(1, "EURUSD", "SilverBullet", "LIMIT", status="ACTIVE",
                          entry=1.1, tp=1.12, sl=1.095, lots=0.1, grade="A+")
        sm.archive_trade(1, 42.5)
        sm.close()

        n = export_journal(db, out)
        self.assertEqual(n, 1)
        with open(out) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["symbol"], "EURUSD")
        self.assertEqual(rows[0]["grade"], "A+")
        self.assertEqual(float(rows[0]["pnl"]), 42.5)
        self.assertEqual(float(rows[0]["entry"]), 1.1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
