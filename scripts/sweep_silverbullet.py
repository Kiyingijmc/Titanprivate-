#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/sweep_silverbullet.py
# Sweep SilverBullet trading-hour windows on the validation harness.
#
# Runs SB-only, all-hours, --shift 0 (so bar hour == broker-server hour),
# per instrument; pools resolved trades; then scores every candidate window
# with a train/test split + Wilson significance. Prints the full ranked table
# (no cherry-picking) so we can see where the edge actually lives.
#
#   .venv/bin/python scripts/sweep_silverbullet.py
# Uses the existing data/history/<SYM>_M5.csv files (offline; no bridge needed).
# ==============================================================================

import asyncio
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "tests", "backtest"))
import backtest_engine as bt  # noqa: E402

SYMS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
        "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]


async def collect():
    bt.TEST_CONFIG["silver_bullet"]["windows"] = [[0, 24]]  # un-gate: all hours
    pooled = []
    for s in SYMS:
        path = f"data/history/{s}_M5.csv"
        if not os.path.exists(path):
            continue
        engine = bt.Backtester(path, shift_hours=0, only="SilverBullet")
        with contextlib.redirect_stdout(io.StringIO()):   # silence per-run report
            trades = await engine.run(costs=False)
        pooled += [t for t in trades if t["outcome"] in ("TP", "SL")]
    return pooled


def _row(ts):
    m = bt.aggregate_metrics(ts)
    p, lo, hi = bt.win_rate_ci(m["wins"], m["trades"])
    return m["trades"], p, m["expectancy"], m["total_r"], lo, hi


def main():
    pooled = asyncio.run(collect())
    print(f"SilverBullet resolved trades (all hours, pooled across {len(SYMS)} instruments): {len(pooled)}\n")

    candidates = [("H%02d" % h, [(h, h + 1)]) for h in range(24)]
    candidates += [("H%02d-%02d" % (h, h + 2), [(h, h + 2)]) for h in range(0, 23, 2)]

    print(f"{'window':12}{'n':>5}{'win%':>6}{'CI':>10}{'expR':>7}{'totR':>7} | "
          f"{'TESTn':>6}{'TESTwin':>8}{'TESTexp':>8}  flag")
    print("-" * 78)
    rows = []
    for name, win in candidates:
        sub = bt.trades_in_window(pooled, win)
        if not sub:
            continue
        train, test = bt.split_trades(sub, 0.7)
        n, p, e, tr, lo, hi = _row(sub)
        tn, tp, te, ttr, tlo, thi = _row(test) if test else (0, 0.0, 0.0, 0.0, 0.0, 0.0)
        rows.append((e, name, n, p, lo, hi, e, tr, tn, tp, te))

    for e, name, n, p, lo, hi, ex, tr, tn, tp, te in sorted(rows, reverse=True):
        flag = "ADOPT?" if (ex > 0 and te > 0 and tn >= 30) else ("insuf" if tn < 30 else "")
        print(f"{name:12}{n:5d}{p*100:6.1f}{f'[{lo*100:.0f}-{hi*100:.0f}]':>10}"
              f"{ex:+7.2f}{tr:+7.1f} | {tn:6d}{tp*100:8.1f}{te:+8.2f}  {flag}")


if __name__ == "__main__":
    main()
