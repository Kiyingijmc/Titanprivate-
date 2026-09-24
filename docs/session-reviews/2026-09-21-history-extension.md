# Historical-data extension: 5–10 years

The exporter now defaults to ten calendar years. `--years 5` through `--years 10`
select the requested depth; `--max-days` remains available as an explicit override.

```bash
.venv/bin/python scripts/export_history.py --all-history --years 10 --import-lake
```

This extends every existing canonical `SYMBOL_TIMEFRAME.csv` in `data/history`,
merges overlapping candles, preserves older saved history, and imports successful
exports into the year-partitioned research lake. CSV replacement is atomic. It
scans the entire interval even if individual windows are empty. Credentials load
from the existing environment or repository `.env`; they are not printed.

For an individual symbol/timeframe, including a new H1 series:

```bash
.venv/bin/python scripts/export_history.py --symbol EURUSD --tf H1 \
  --out data/history/EURUSD_H1.csv --years 10 --import-lake
```

Lake pruning now retains ten years by default, both through the CLI and Python
API. Frozen research datasets and the live trading warmup are unchanged.

## Actual download status

The ten-year batch was attempted, but the configured MT5 HTTP bridge timed out,
including on a separate recent-history probe. No extended candles were downloaded
and no existing history CSVs were replaced. `data/history/coverage.json` records
the failed request; `data/history/inventory.json` records existing local coverage.
Saved M5 datasets span roughly three years, and saved D1 datasets roughly five.

The Windows MT5 terminal and Titan HTTP bridge must be reachable to resume the
command above. Requesting ten years does not establish that the broker retains
that much data: inspect the resulting coverage report's earliest/latest dates,
span, and `reaches_requested_start` flag. A date span alone does not prove a gap-free
series. No synthetic or alternate-provider candles were mixed into broker history.

## Validation and inventory

38 targeted exporter, retention, and lake-import tests passed. Current inventory:
27 symbol/timeframe series, 4,299,277 candles; overall dates 2021-05-18 through
2026-07-28. Per-series dates are recorded in `data/history/inventory.json`.
