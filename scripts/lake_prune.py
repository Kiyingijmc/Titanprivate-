#!/usr/bin/env python3
# scripts/lake_prune.py
# Retention pruning for the research lake (src/data/lake.py). Dry-run by
# default (prints candidates only); pass --execute to actually delete.
#
#   .venv/bin/python scripts/lake_prune.py                    # dry-run
#   .venv/bin/python scripts/lake_prune.py --execute           # deletes
#   .venv/bin/python scripts/lake_prune.py --active-years 2 --unused-days 90 --execute
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.data.lake import Lake  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prune research-lake partitions that are both older than --active-years "
                     "and unused for --unused-days. Dry-run by default; pass --execute to delete."
    )
    p.add_argument("--lake-root", default="data/lake")
    p.add_argument("--active-years", type=int, default=4)
    p.add_argument("--unused-days", type=int, default=180)
    p.add_argument("--execute", action="store_true", help="actually delete (default: dry-run)")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    lake = Lake(args.lake_root)

    result = lake.prune(
        active_years=args.active_years,
        unused_days=args.unused_days,
        dry_run=not args.execute,
    )

    verb = "deleted" if args.execute else "candidate"
    for path in result:
        print(f"[LAKE_PRUNE] {verb}: {path}")

    if args.execute:
        print(f"[LAKE_PRUNE] summary: deleted {len(result)} partition(s)")
    else:
        print(f"[LAKE_PRUNE] summary: {len(result)} partition(s) eligible for deletion "
              f"(dry-run; pass --execute to delete)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
