#!/usr/bin/env python
"""
Trade journal export: dumps the persistent trade_history (entry/SL/TP/lots/
grade/PnL per ticket) to CSV for review, tax records, or spreadsheet analysis.

Usage:
    .venv/bin/python scripts/export_journal.py                       # default paths
    .venv/bin/python scripts/export_journal.py --db data/db/trade_state.db --out data/journal.csv
"""
import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

COLUMNS = ["ticket_id", "symbol", "strategy", "grade", "lots",
           "entry", "sl", "tp", "pnl", "close_time", "comment"]


def export_journal(db_path, out_path):
    """Writes trade_history to CSV; returns the number of rows exported."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM trade_history ORDER BY close_time ASC").fetchall()
    finally:
        conn.close()

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            rec = dict(r)
            ts = rec.get("close_time") or 0
            rec["close_time"] = datetime.fromtimestamp(ts).isoformat(sep=" ") if ts else ""
            w.writerow([rec.get(c, "") for c in COLUMNS])
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export the Titan trade journal to CSV.")
    ap.add_argument("--db", default="data/db/trade_state.db")
    ap.add_argument("--out", default="data/journal.csv")
    args = ap.parse_args(argv)

    if not Path(args.db).exists():
        print(f"[ERROR] Database not found: {args.db}")
        return 1
    n = export_journal(args.db, args.out)
    print(f"Exported {n} closed trades -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
