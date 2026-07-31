#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/swap_survey.py
# Ledger Step-0 — FBS swap survey (arsenal 05-STRATEGY-ARSENAL §9, STRAT-06 data).
#
# Pulls SYMBOL_SWAP_LONG/SHORT (+ mode, contract, mid) for the configured
# 12-pair universe over the Windows HTTP bridge — no EA recompile — computes
# annualised carry for both sides, appends a dated row per symbol to an
# append-only CSV log (nightly re-runs accumulate the observation window,
# capturing broker swap revisions), and prints the pre-registered gate:
#
#   GATE: does ANY symbol offer net positive carry > 3% annualised
#         after the broker's markup?  NO -> delete the Ledger idea.
#
# Annualisation convention: 364 swap applications/year (52w x 7; the triple
# rollover day means 7 applications across 5 trading days). MT5 swap modes:
#   0 disabled | 1 points | 2 base ccy/lot | 3 margin ccy/lot | 4 deposit
#   ccy/lot | 5/6 annual interest %. Modes 3/4 are computed assuming the
#   money currency matches the quote side of `mid` — flagged approximate.
#
#   set -a; source .env; set +a
#   .venv/bin/python scripts/swap_survey.py                # survey + gate
#   .venv/bin/python scripts/swap_survey.py --symbols EURUSD XAUUSD
# ==============================================================================
import argparse
import asyncio
import csv
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import yaml                                                     # noqa: E402
from src.execution.broker.mt5_http import MT5HttpBroker         # noqa: E402
from src.execution.broker.errors import BrokerError             # noqa: E402

NIGHTS_PER_YEAR = 364
GATE_PCT = 3.0
LOG_PATH = "data/results/swap_survey/swap_log.csv"
FIELDS = ["date", "sym", "mode", "swap_long", "swap_short", "mid",
          "contract_size", "point", "carry_long_pct", "carry_short_pct", "exact"]


def annualised_carry_pct(*, mode, rate, point, mid, contract_size):
    """(annualised carry %, exact?) for one side; (None, True) if uncomputable.

    Positive = you are PAID to hold that side for a year, as % of notional.
    """
    if mode == 0 or rate == 0:
        return (None, True) if mode == 0 else (0.0, True)
    if mode == 1:                                   # points
        if mid <= 0:
            return None, True
        return rate * point * NIGHTS_PER_YEAR / mid * 100.0, True
    if mode == 2:                                   # base currency per lot
        if contract_size <= 0:
            return None, True
        return rate * NIGHTS_PER_YEAR / contract_size * 100.0, True
    if mode in (3, 4):                              # margin/deposit ccy per lot
        notional = contract_size * mid
        if notional <= 0:
            return None, False
        return rate * NIGHTS_PER_YEAR / notional * 100.0, False
    if mode in (5, 6):                              # already annual interest %
        return rate, True
    return None, False                              # exotic modes: report raw only


def gate(rows):
    """Pre-registered Step-0 gate: any side strictly above +3% annualised."""
    winners = []
    for r in rows:
        for side, key in (("LONG", "carry_long_pct"), ("SHORT", "carry_short_pct")):
            pct = r.get(key)
            if pct is not None and pct > GATE_PCT:
                winners.append((r["sym"], side, pct))
    return bool(winners), winners


def append_log(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def config_pairs():
    with open("config/config.yaml") as f:
        cfg = yaml.safe_load(f)
    return list(cfg["strategies"]["silver_bullet"]["pairs"])


async def survey(symbols):
    rows = []
    today = date.today().isoformat()
    async with MT5HttpBroker() as b:
        for sym in symbols:
            try:
                info = await b.get_symbol_info(sym)
                tick = await b.get_current_tick(sym)
            except BrokerError as e:
                print(f"[SKIP] {sym}: {type(e).__name__}: {e}")
                continue
            mid = (tick.bid + tick.ask) / 2.0
            long_pct, exact_l = annualised_carry_pct(
                mode=info.swap_mode, rate=info.swap_long, point=info.point,
                mid=mid, contract_size=info.contract_size)
            short_pct, exact_s = annualised_carry_pct(
                mode=info.swap_mode, rate=info.swap_short, point=info.point,
                mid=mid, contract_size=info.contract_size)
            rows.append({
                "date": today, "sym": sym, "mode": info.swap_mode,
                "swap_long": info.swap_long, "swap_short": info.swap_short,
                "mid": round(mid, info.digits), "contract_size": info.contract_size,
                "point": info.point,
                "carry_long_pct": None if long_pct is None else round(long_pct, 3),
                "carry_short_pct": None if short_pct is None else round(short_pct, 3),
                "exact": exact_l and exact_s,
            })
    return rows


def fmt_pct(v, exact):
    if v is None:
        return "     n/a"
    return f"{v:+7.2f}%" + ("" if exact else "~")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--log", default=LOG_PATH)
    a = ap.parse_args()
    symbols = a.symbols or config_pairs()

    print(f"### Ledger Step-0 swap survey — {len(symbols)} symbols, "
          f"{NIGHTS_PER_YEAR} nights/yr convention ###\n")
    rows = asyncio.run(survey(symbols))
    if not rows:
        print("No data — is the bridge up? (scripts/check_bridge_http.py)")
        sys.exit(1)

    print(f"{'sym':8} {'mode':4} {'swap_long':>10} {'swap_short':>10} "
          f"{'carry_long':>9} {'carry_short':>10}")
    for r in rows:
        print(f"{r['sym']:8} {r['mode']:4} {r['swap_long']:>10} "
              f"{r['swap_short']:>10} {fmt_pct(r['carry_long_pct'], r['exact']):>9} "
              f"{fmt_pct(r['carry_short_pct'], r['exact']):>10}")

    append_log(a.log, rows)
    print(f"\n[LOG] appended {len(rows)} rows -> {a.log}")

    passed, winners = gate(rows)
    print("\n" + "=" * 70)
    if passed:
        print(f"GATE: PASS — net carry > {GATE_PCT}% annualised on:")
        for sym, side, pct in winners:
            print(f"  {sym} {side} {pct:+.2f}%")
        print("Proceed to Ledger design (D1 momentum filter etc., arsenal §9).")
    else:
        print(f"GATE: FAIL — no symbol offers > {GATE_PCT}% annualised net carry.")
        print("Per pre-registration: stop; the Ledger idea dies. The swap table")
        print("above still feeds STRAT-06 (backtester swap model).")
    print("(~ = approximate: money-mode swap assumed in the quote currency)")


if __name__ == "__main__":
    main()
