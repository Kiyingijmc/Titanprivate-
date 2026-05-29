#!/usr/bin/env python3
# H4 trend-following proof-of-concept (Donchian breakout, structural 2xATR stop).
# Screens net-of-cost, out-of-sample edge across instruments. NOT a live strategy.
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "tests", "backtest"))
import backtest_engine as bt  # noqa: E402


def resample_h4(m5_df):
    df = m5_df.copy()
    tcol = "time" if "time" in df.columns else "datetime"  # exported CSVs use 'datetime'
    df["time"] = pd.to_datetime(df[tcol])
    df = df.set_index("time")
    h4 = df.resample("4h").agg({"open": "first", "high": "max",
                                "low": "min", "close": "last"}).dropna()
    return h4.reset_index()


def atr_series(h4, period=14):
    h, l, c = h4["high"], h4["low"], h4["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def donchian_signals(h4, n=20):
    highs = h4["high"].values
    lows = h4["low"].values
    closes = h4["close"].values
    out = []
    for i in range(n, len(h4)):
        upper = highs[i - n:i].max()
        lower = lows[i - n:i].min()
        if closes[i] > upper:
            out.append((i, "LONG"))
        elif closes[i] < lower:
            out.append((i, "SHORT"))
    return out


def simulate_flip(signals, bars, atrs, stop_mult=2.0):
    """Signal-flip trend sim: enter at next-bar open on a breakout; exit at -1R if the
    structural stop is hit, else at the bar where the opposite signal fires. One position
    at a time. Returns trade dicts with entry/sl/r/outcome/entry_idx/exit_idx."""
    sig_at = dict(signals)
    trades = []
    pos = None
    n = len(bars)
    for i in range(n):
        b = bars[i]
        if pos:
            if pos["dir"] == "LONG" and b["low"] <= pos["sl"]:
                trades.append({**pos, "exit_idx": i, "r": -1.0, "outcome": "SL"}); pos = None
            elif pos["dir"] == "SHORT" and b["high"] >= pos["sl"]:
                trades.append({**pos, "exit_idx": i, "r": -1.0, "outcome": "SL"}); pos = None
        s = sig_at.get(i)
        if s:
            if pos and s != pos["dir"]:
                px = b["close"]
                r = ((px - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - px)) / pos["risk"]
                trades.append({**pos, "exit_idx": i, "r": r, "outcome": "FLIP"}); pos = None
            if pos is None and i + 1 < n:
                entry = bars[i + 1]["open"]
                risk = stop_mult * atrs[i]
                if risk > 0:
                    sl = entry - risk if s == "LONG" else entry + risk
                    pos = {"dir": s, "entry": entry, "sl": sl, "risk": risk, "entry_idx": i + 1}
    return trades


def net_r_after_costs(r, entry, sl, spread_price, tick_size, tick_value, comm_rt=14.0):
    """R net of cost: 2x spread crossing (fraction of the stop) + round-turn commission in R."""
    stop = abs(entry - sl)
    if stop <= 0:
        return r
    money_per_lot = (stop / tick_size) * tick_value
    cost = 2 * spread_price / stop + (comm_rt / money_per_lot if money_per_lot > 0 else 0.0)
    return r - cost


SYMS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
        "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]
# Typical weekday spreads in price (confirm live later); wide structural stops -> robust.
SPREAD = {"EURUSD": 0.00010, "GBPUSD": 0.00016, "USDJPY": 0.013, "AUDUSD": 0.00016,
          "USDCAD": 0.00020, "GBPCAD": 0.00040, "GBPJPY": 0.025, "XAUUSD": 0.25,
          "US30": 2.0, "BTCUSD": 8.0, "XBRUSD": 0.03}


def _signals_to_dicts(signals, h4, atrs, stop_mult=2.0, rr=3.0):
    """Build resolve_trade-style signal dicts (fixed-RR variant) from Donchian breakouts."""
    out = []
    for i, d in signals:
        risk = stop_mult * atrs[i]
        if not (risk > 0):
            continue
        entry = float(h4["close"].iloc[i])
        is_long = d == "LONG"
        sl = entry - risk if is_long else entry + risk
        tp = entry + rr * risk if is_long else entry - rr * risk
        out.append({"bar_idx": i, "dir": "BUY" if is_long else "SELL", "cmd": "MARKET",
                    "entry": entry, "sl": sl, "tp": tp, "ttl_bars": 1})
    return out


def _net(trades, sym):
    """Attach net-of-cost R to each trade using sym specs + typical spread."""
    import json
    sp = SPREAD.get(sym, 0.0002)
    specs = json.load(open("data/specs.json")) if os.path.exists("data/specs.json") else {}
    spec = specs.get(sym, {"tick_size": 1e-5, "tick_value": 1.0})
    for t in trades:
        t["r"] = net_r_after_costs(t["r"], t["entry"], t["sl"], sp,
                                   spec["tick_size"], spec["tick_value"])
        t["outcome"] = "TP" if t["r"] > 0 else "SL"   # so aggregate_metrics counts it
    return trades


def main():
    flip_all, rr_all = [], []
    for s in SYMS:
        path = f"data/history/{s}_M5.csv"
        if not os.path.exists(path):
            continue
        m5 = pd.read_csv(path)
        h4 = resample_h4(m5)
        atrs = atr_series(h4).fillna(0.0).values
        sigs = donchian_signals(h4, n=20)
        flip_all += _net(simulate_flip(sigs, h4.to_dict("records"), atrs, stop_mult=2.0), s)
        rr = bt.simulate_signals(_signals_to_dicts(sigs, h4, atrs),
                                 h4[["open", "high", "low", "close"]].to_dict("records"))
        rr_all += _net(rr, s)

    def report(name, trades):
        m = bt.aggregate_metrics(trades)
        p, lo, hi = bt.win_rate_ci(m["wins"], m["trades"])
        norm = [{**t, "bar_idx": t.get("entry_idx", t.get("bar_idx", 0))} for t in trades]
        _, test = bt.split_trades(norm, 0.7)
        mt = bt.aggregate_metrics(test)
        pt, _, _ = bt.win_rate_ci(mt["wins"], mt["trades"])
        flag = " [insuf n<30]" if m["trades"] < 30 else ""
        print(f"{name:14} n={m['trades']:4d} win={p*100:4.1f}% CI[{lo*100:.0f}-{hi*100:.0f}] "
              f"netExpR={m['expectancy']:+.3f} totR={m['total_r']:+.1f} PF={m['profit_factor']:.2f} "
              f"DD={m['max_drawdown_r']:.0f}R | TEST n={mt['trades']} exp={mt['expectancy']:+.3f}{flag}")

    print("H4 Donchian(20) trend PoC -- NET OF COSTS, pooled across instruments\n")
    report("SIGNAL-FLIP", flip_all)
    report("FIXED-3R", rr_all)


if __name__ == "__main__":
    main()
