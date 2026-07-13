#!/usr/bin/env python3
# scripts/lake_import.py
# Import CSV history into the research lake (src/data/lake.py). Reads both
# CSV shapes present in this repo:
#   - MT5 tab export (test_data.csv):  <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>
#   - comma history export (data/history/*_M5.csv): datetime,open,high,low,close[,volume]
# Normalizes both to time/open/high/low/close(+volume) and hands off to Lake.ingest.
#
#   .venv/bin/python scripts/lake_import.py --csv test_data.csv --symbol BTCUSD --tf M5
#   .venv/bin/python scripts/lake_import.py --all-history
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pandas as pd  # noqa: E402

from src.data.lake import Lake  # noqa: E402

_TF_CHOICES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
_FNAME_RE = re.compile(
    r"^(?P<symbol>[A-Za-z0-9]+)_(?P<tf>" + "|".join(_TF_CHOICES) + r")\.csv$",
    re.IGNORECASE,
)
_ALL_HISTORY_TFS = ("M5", "H1", "D1")


def infer_symbol_tf(path: Path):
    """Infer (symbol, tf) from a filename like EURUSD_M5.csv; None if it
    doesn't match the SYMBOL_TF.csv convention (e.g. *_report.txt, *_trades.csv)."""
    m = _FNAME_RE.match(Path(path).name)
    if not m:
        return None
    return m.group("symbol"), m.group("tf").upper()


def sniff_and_read(path) -> pd.DataFrame:
    """Read a CSV in either supported shape and normalize to
    time/open/high/low/close(+volume) columns."""
    path = Path(path)
    with open(path, "r") as f:
        header = f.readline()

    if "\t" in header or header.strip().startswith("<DATE>"):
        return _read_mt5_tab(path)
    return _read_comma_datetime(path)


def _read_mt5_tab(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    missing = [c for c in ("date", "time", "open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: MT5 tab export missing expected columns: {missing}")

    time = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str), errors="raise")
    out = pd.DataFrame({
        "time": time,
        "open": df["open"],
        "high": df["high"],
        "low": df["low"],
        "close": df["close"],
    })
    if "tickvol" in df.columns:
        out["volume"] = df["tickvol"]
    return out


def _read_comma_datetime(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    if "time" not in df.columns and "datetime" in df.columns:
        df = df.rename(columns={"datetime": "time"})

    missing = [c for c in ("time", "open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: CSV missing expected columns: {missing}")

    keep = ["time", "open", "high", "low", "close"]
    if "volume" in df.columns:
        keep.append("volume")
    return df[keep]


def _ingest_file(lake: Lake, path: Path, symbol: str, tf: str, broker: str, source: str) -> list:
    df = sniff_and_read(path)
    return lake.ingest(df, broker=broker, symbol=symbol, tf=tf, source=source or str(path))


def _report_written(lake: Lake, written: list, broker: str, symbol: str, tf: str) -> None:
    manifest = lake.manifest()
    for p in written:
        year = Path(p).stem
        entry = manifest.get(broker, {}).get(symbol, {}).get(tf, {}).get(year, {})
        rows = entry.get("rows", "?")
        print(f"[LAKE_IMPORT] wrote {p} rows={rows}")


def _import_one(lake: Lake, args) -> int:
    path = Path(args.csv)
    try:
        written = _ingest_file(lake, path, args.symbol, args.tf, args.broker, args.source)
    except Exception as e:  # noqa: BLE001 - CLI boundary, report and exit
        print(f"[LAKE_IMPORT] ERROR: {path}: {e}")
        return 1
    _report_written(lake, written, args.broker, args.symbol, args.tf)
    return 0


def _import_all_history(lake: Lake, args) -> int:
    hist_dir = Path(args.history_dir)
    files = sorted({f for tf in _ALL_HISTORY_TFS for f in hist_dir.glob(f"*_{tf}.csv")})

    ok = 0
    failed = 0
    for path in files:
        inferred = infer_symbol_tf(path)
        if inferred is None:
            print(f"[LAKE_IMPORT] SKIP {path}: cannot infer symbol/tf from filename")
            failed += 1
            continue
        symbol, tf = inferred
        try:
            written = _ingest_file(lake, path, symbol, tf, args.broker, args.source)
        except Exception as e:  # noqa: BLE001 - continue-on-error across the batch
            print(f"[LAKE_IMPORT] FAILED {path}: {e}")
            failed += 1
            continue
        _report_written(lake, written, args.broker, symbol, tf)
        ok += 1

    print(f"[LAKE_IMPORT] summary: {ok} ok, {failed} failed, {len(files)} total")
    return 0 if ok >= 1 else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import CSV history into the research lake.")
    p.add_argument("--csv", help="path to a single CSV file to import")
    p.add_argument("--symbol", help="broker symbol (required with --csv)")
    p.add_argument("--tf", choices=_TF_CHOICES, help="timeframe (required with --csv)")
    p.add_argument("--broker", default="fbs")
    p.add_argument("--source", default="", help="manifest source note (defaults to the CSV path)")
    p.add_argument("--lake-root", default="data/lake")
    p.add_argument("--all-history", action="store_true",
                    help="glob data/history/*_{M5,H1,D1}.csv, inferring symbol/tf per file")
    p.add_argument("--history-dir", default="data/history", help="directory for --all-history")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    lake = Lake(args.lake_root)

    if args.all_history:
        return _import_all_history(lake, args)

    if not args.csv or not args.symbol or not args.tf:
        _build_parser().error("--csv, --symbol and --tf are required unless --all-history is given")
    return _import_one(lake, args)


if __name__ == "__main__":
    sys.exit(main())
