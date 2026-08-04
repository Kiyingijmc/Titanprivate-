"""Build the screen's signal population.

Deliberately does NOT call poc_sb_stops.resolve(): that function applies a
`busy_until` one-open-per-symbol cursor, a limit-fill filter and a 12-bar
expiry drop. All three select on post-signal events and would bias the
sampling frame (spec §2.7). We take collect_signals()'s raw output instead.
"""
from scripts.confidence_screen import ATR10_MULT, RR


def add_stop_and_target(sig):
    """Attach the live (ATR10) stop, the fixed 2R target, and risk."""
    atr = float(sig["atr"])
    if atr <= 0.0:
        raise ValueError(f"signal at bar {sig.get('bar_idx')} has non-positive ATR {atr!r}")
    entry = float(sig["entry"])
    dist = ATR10_MULT * atr
    is_long = sig["dir"] == "BUY"
    sl = entry - dist if is_long else entry + dist
    risk = abs(entry - sl)
    tp = entry + RR * risk if is_long else entry - RR * risk
    return {**sig, "sl": sl, "tp": tp, "risk": risk}


def build_population(symbols, collect=None, tf="H1", quick=False):
    """Every signal for every symbol — no fill, expiry or overlap filtering."""
    if collect is None:
        from scripts.poc_sb_stops import collect_signals as collect
    population = []
    for sym in symbols:
        signals, _bars = collect(sym, quick=quick, tf=tf)
        if not signals:
            continue
        for sig in signals:
            population.append(add_stop_and_target({**sig, "symbol": sym}))
    return population
