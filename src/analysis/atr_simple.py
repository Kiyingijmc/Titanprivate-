"""last_atr: simple ATR (mean of the last `period` true ranges).

Deliberately self-contained: arsenal strategies compute their own ATR from
raw OHLC instead of reading the SMC enrichment's ATR column, so they stay
independent of the smc pack (spec 5.2). Deterministic, stdlib-only.
"""


def last_atr(df, period=14) -> float:
    n = len(df)
    if n < 2:
        return 0.0
    lo = max(1, n - period)
    highs = df["high"].tolist()[lo - 1:]
    lows = df["low"].tolist()[lo - 1:]
    closes = df["close"].tolist()[lo - 1:]
    trs = []
    for i in range(1, len(highs)):
        h, l, pc = float(highs[i]), float(lows[i]), float(closes[i - 1])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return (sum(trs) / len(trs)) if trs else 0.0
