"""Weekday-based trading-day calendar for the Almanac turn-of-month canary.

Trading day == Monday-Friday. Exchange holidays are deliberately NOT modelled:
the Almanac canary needs one deterministic rule applied identically live and
in replay, and a holiday feed would add a divergence source of its own. The
approximation is documented in docs/strategies/almanac.md.

All functions are pure (dates in, values out) so both the strategy's entry
gate and TradeManager's time exit share the exact same calendar.
"""
from datetime import date, timedelta


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5


def trading_day_index(d: date) -> int:
    """1-based index of `d` among the weekdays of its month; 0 for weekends."""
    if not is_trading_day(d):
        return 0
    return sum(
        1 for day in range(1, d.day + 1)
        if date(d.year, d.month, day).weekday() < 5
    )


def last_trading_day(year: int, month: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def is_last_trading_day(d: date) -> bool:
    return d == last_trading_day(d.year, d.month)


def effective_trading_day(d: date) -> date:
    """`d` itself on a weekday, else the most recent prior weekday."""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def should_time_exit(current: date, entry: date, exit_trading_day: int = 3) -> bool:
    """Time exit for a position entered on the last trading day of `entry`'s
    month: True from the first trading day AFTER `exit_trading_day` of the
    following month onward (exit at the start of TD4 with the default of 3 --
    the documented approximation of "close of TD3"). A hold that somehow
    survives past the following month always exits.
    """
    if (current.year, current.month) == (entry.year, entry.month):
        return False  # entry day, or the trailing weekend of the entry month
    eff = effective_trading_day(current)
    if (eff.year, eff.month) == (entry.year, entry.month):
        return False  # weekend spilling over the month boundary
    months_apart = (current.year - entry.year) * 12 + (current.month - entry.month)
    if months_apart > 1:
        return True   # runaway hold -- close unconditionally
    return trading_day_index(eff) > exit_trading_day
