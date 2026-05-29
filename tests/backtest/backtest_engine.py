# ==============================================================================
# FILE: tests/backtest/backtest_engine.py
# TYPE: PERFORMANCE UPDATE (Simulation)
# AUDIT: 
#   1. Fixed Duplicate Column Crash (handling CSVs with redundant volume headers).
#   2. Fixed H1 Index Naming issues.
#   3. Optimized Pre-calc & Resampling logic.
# STATUS: DEBUGGED & PRODUCTION READY
# ==============================================================================

import pandas as pd
import sys
import os
import asyncio
import time
from datetime import timedelta

# 1. Setup System Path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# 2. Logic Imports
from src.strategies.models.silver_bullet import SilverBullet
from src.strategies.models.unicorn import UnicornModel
from src.strategies.models.ict_ote import ICT_OTE
from src.strategies.models.crt import CandleRangeTheory
from src.analysis.bias_engine import BiasEngine
from src.analysis.smc_analyzer import SMCAnalyzer

def resolve_trade(signal, future_bars):
    """Resolve one signal into an outcome over the bars that follow it.

    signal: {dir 'BUY'/'SELL', cmd 'MARKET'/'LIMIT', entry, sl, tp, ttl_bars}.
    future_bars: ordered dicts with open/high/low/close, strictly after the signal bar.
    Returns {filled, outcome, r, fill_offset, exit_offset}; outcome in
    {TP, SL, EXPIRED, OPEN_AT_END, INVALID}. R = SL -> -1.0, TP -> +|tp-entry|/risk.
    Lives with the backtester (tests/backtest) by design; not used by live src/ code.
    """
    entry = float(signal["entry"])
    sl = float(signal["sl"])
    tp = float(signal["tp"])
    if signal["dir"] not in ("BUY", "SELL"):
        return {"filled": False, "outcome": "INVALID", "r": 0.0, "fill_offset": None, "exit_offset": 0}
    risk = abs(entry - sl)
    if risk == 0:
        return {"filled": False, "outcome": "INVALID", "r": 0.0, "fill_offset": None, "exit_offset": 0}

    is_long = signal["dir"] == "BUY"
    n = len(future_bars)
    if n == 0:
        return {"filled": False, "outcome": "OPEN_AT_END", "r": 0.0, "fill_offset": None, "exit_offset": 0}

    # 1. Fill.
    if signal["cmd"] == "MARKET":
        fill_offset = 0
    else:  # LIMIT: filled when a bar's range touches entry, within TTL.
        ttl = min(int(signal["ttl_bars"]), n)
        fill_offset = None
        for k in range(ttl):
            b = future_bars[k]
            if b["low"] <= entry <= b["high"]:
                fill_offset = k
                break
        if fill_offset is None:
            return {"filled": False, "outcome": "EXPIRED", "r": 0.0,
                    "fill_offset": None, "exit_offset": max(0, ttl - 1)}  # exit_offset marks the last bar the resting limit occupied (its TTL window) so the caller can free the symbol

    # 2. Resolve SL/TP from the fill bar onward (inclusive). Same bar both hit -> SL.
    for j in range(fill_offset, n):
        b = future_bars[j]
        if is_long:
            sl_hit = b["low"] <= sl
            tp_hit = b["high"] >= tp
        else:
            sl_hit = b["high"] >= sl
            tp_hit = b["low"] <= tp
        if sl_hit:
            return {"filled": True, "outcome": "SL", "r": -1.0,
                    "fill_offset": fill_offset, "exit_offset": j}
        if tp_hit:
            return {"filled": True, "outcome": "TP", "r": abs(tp - entry) / risk,
                    "fill_offset": fill_offset, "exit_offset": j}

    # 3. Never resolved.
    return {"filled": True, "outcome": "OPEN_AT_END", "r": 0.0,
            "fill_offset": fill_offset, "exit_offset": n - 1}


def aggregate_metrics(trades):
    """Summarise resolved trades (TP/SL only) in R-multiples."""
    resolved = [t for t in trades if t["outcome"] in ("TP", "SL")]
    wins = [t["r"] for t in resolved if t["r"] > 0]
    losses = [t["r"] for t in resolved if t["r"] < 0]
    total_r = sum(t["r"] for t in resolved)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    equity = peak = max_dd = 0.0
    for t in resolved:
        equity += t["r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    streak = max_streak = 0
    for t in resolved:
        if t["r"] < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    n = len(resolved)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / n) if n else 0.0,
        "expectancy": (total_r / n) if n else 0.0,
        "total_r": total_r,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "max_drawdown_r": max_dd,
        "max_losing_streak": max_streak,
        "expired": sum(1 for t in trades if t["outcome"] == "EXPIRED"),
        "open_at_end": sum(1 for t in trades if t["outcome"] == "OPEN_AT_END"),
    }


def simulate_signals(signals, bars):
    """Resolve signals under one-open-per-symbol concurrency.

    signals: chronologically ordered, each with bar_idx + resolve_trade fields.
    bars: full 0-indexed list of OHLC dicts (positionally aligned with bar_idx).
    Returns trade dicts (signal fields merged with the resolution).
    """
    trades = []
    busy_until = -1
    for sig in signals:
        if sig["bar_idx"] <= busy_until:
            continue  # a trade/limit is live for this symbol
        future = bars[sig["bar_idx"] + 1:]
        res = resolve_trade(sig, future)
        if res["outcome"] == "INVALID":
            continue  # never placed -> does not occupy the symbol
        trades.append({**sig, **res})
        busy_until = sig["bar_idx"] + 1 + res["exit_offset"]
    return trades


# 3. Mock Logger for Backtesting (Silent)
class MockLogger:
    def log_event(self, t, m, msg, p=None): pass

# Config
TEST_CONFIG = {
    'silver_bullet': {'enabled': True, 'session_ny': ["10:00", "11:00"]},
    'unicorn_model': {'enabled': True},
    'ict_ote': {'enabled': True},
    'crt': {'enabled': True}
}

class Backtester:
    """
    High-Performance Titan Backtest Engine.
    
    AUDIT FIX:
    - Enforces Numeric Types (cleaning dirty strings).
    - Removes Duplicate Columns to prevent pandas crashes.
    """
    def __init__(self, csv_path, shift_hours=-7):
        self.csv_path = csv_path
        self.shift_hours = shift_hours
        self.logger = MockLogger()
        self.strategies = []
        self.m5_df = pd.DataFrame()
        self.h1_df = pd.DataFrame()
        
        self._load_and_process_data()
        self._init_strategies()

    def _load_and_process_data(self):
        print(f"\n[LOAD] Reading {self.csv_path}...")
        try:
            # Flexible delimiter support
            try:
                df = pd.read_csv(self.csv_path)
                if len(df.columns) < 2: 
                    df = pd.read_csv(self.csv_path, sep='\t')
            except Exception as e:
                print(f"[ERROR] CSV Parsing failed: {e}")
                sys.exit(1)
            
            # Clean Headers
            df.columns = [c.replace("<","").replace(">","").lower().strip() for c in df.columns]
            
            # Robust Date Parsing
            if 'date' in df.columns and 'time' in df.columns:
                combined_str = df['date'].astype(str) + ' ' + df['time'].astype(str)
                df['datetime'] = pd.to_datetime(combined_str, errors='coerce')
            elif 'datetime' in df.columns:
                df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
            else:
                combined_str = df.iloc[:,0].astype(str) + ' ' + df.iloc[:,1].astype(str)
                df['datetime'] = pd.to_datetime(combined_str, errors='coerce')
            
            # Drop bad dates
            df = df.dropna(subset=['datetime'])

            # Time Shift (Broker to NY)
            if self.shift_hours != 0:
                print(f"[TIME] Shifting timestamps by {self.shift_hours} hours...")
                df['datetime'] = df['datetime'] + timedelta(hours=self.shift_hours)
            
            df = df.set_index('datetime').sort_index()
            
            # Standardize Column Names
            rename_map = {'vol': 'tick_volume', 'tickvol': 'tick_volume', 'v': 'tick_volume'}
            df.rename(columns=rename_map, inplace=True)
            
            # AUDIT FIX: Deduplicate Columns
            # If CSV had both 'vol' and 'tickvol', we now have two 'tick_volume' columns.
            # We keep only the first one to prevent dataframe-return errors in to_numeric.
            df = df.loc[:, ~df.columns.duplicated()]
            
            # Keep required columns
            cols_to_keep = ['open', 'high', 'low', 'close', 'tick_volume']
            # Only keep columns that actually exist in the dataframe
            available = [c for c in cols_to_keep if c in df.columns]
            df = df[available]
            
            # Force Numeric Types (removes headers appearing in data rows)
            for col in available:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
            df = df.dropna()
            
            if 'tick_volume' not in df.columns: df['tick_volume'] = 1
            
            # Store M5
            self.m5_df = df.reset_index().rename(columns={'datetime': 'time'})
            
            print("[GEN] Generating H1 Context Data...")
            
            # Create a temporary DF indexed by time
            temp_idx = self.m5_df.set_index('time')
            # Ensure index is datetime (redundant but safe)
            temp_idx.index = pd.to_datetime(temp_idx.index)
            
            # Resample
            resampler = temp_idx.resample('1h')
            
            # Aggregation (Safe)
            h1_temp = resampler.agg({
                'high': 'max',
                'low': 'min',
                'tick_volume': 'sum'
            })
            h1_temp['open'] = resampler['open'].first()
            h1_temp['close'] = resampler['close'].last()
            
            # Reset Index & Force Name 'time'
            self.h1_df = h1_temp.dropna().reset_index()
            
            # Safe Rename of index column (Column 0)
            cols = list(self.h1_df.columns)
            cols[0] = 'time'
            self.h1_df.columns = cols

            print(f"[READY] M5 Bars: {len(self.m5_df)} | H1 Bars: {len(self.h1_df)}")

        except Exception as e:
            print(f"[ERROR] Data Processing Failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def _init_strategies(self):
        self.strategies.append(SilverBullet(TEST_CONFIG['silver_bullet'], self.logger))
        self.strategies.append(UnicornModel(TEST_CONFIG['unicorn_model'], self.logger))
        self.strategies.append(ICT_OTE(TEST_CONFIG['ict_ote'], self.logger))
        self.strategies.append(CandleRangeTheory(TEST_CONFIG['crt'], self.logger))

    async def run(self, trades_out=None):
        print("\n--- STARTING OPTIMIZED BACKTEST ---")
        start_time = time.time()
        signals = []
        
        # Pre-calc Indicators
        print("[MATH] Pre-calculating SMC Vectors...")
        smc = SMCAnalyzer(self.m5_df)
        enriched_m5 = smc.process()
        
        window_size = 400 
        total_bars = len(enriched_m5)

        if total_bars < window_size:
            print(f"Not enough data. Need {window_size}, got {total_bars}")
            return

        print(f"[SIM] Running simulation on {total_bars} bars...")
        
        # Ensure H1 time is datetime for filtering
        self.h1_df['time'] = pd.to_datetime(self.h1_df['time'])

        for i in range(window_size, total_bars):
            current_window = enriched_m5.iloc[i-window_size : i+1]
            current_time = current_window.iloc[-1]['time']

            # Context slice
            h1_context = self.h1_df[self.h1_df['time'] < current_time]
            
            htf_bias = "NEUTRAL"
            liquidity = {}

            if len(h1_context) > 20:
                bias_eng = BiasEngine(h1_context.iloc[-100:]) 
                htf_bias, liquidity = bias_eng.get_bias_context()

            ctx = {
                'bias': htf_bias,
                'liquidity': liquidity,
                'ny_time': current_time.strftime("%H:%M:%S")
            }
            
            for strat in self.strategies:
                decision = await strat.on_new_candle(current_window, context=ctx)
                
                if decision:
                    sig_type = decision['signal']

                    if strat.name != "CRT":
                        if (htf_bias == "BULLISH" and sig_type == "SELL") or \
                           (htf_bias == "BEARISH" and sig_type == "BUY"):
                               continue

                    signals.append({
                        'time': current_time,
                        'strat': strat.name,
                        'dir': sig_type,
                        'cmd': decision['type'],
                        'entry': float(decision['price']),
                        'sl': float(decision['sl']),
                        'tp': float(decision['tp']),
                        'ttl_bars': 12 if "Silver" in strat.name else 24,
                        'bar_idx': i,
                    })

        bars = enriched_m5[['open', 'high', 'low', 'close']].to_dict('records')
        trades = simulate_signals(signals, bars)
        duration = time.time() - start_time
        self._report(trades, duration, trades_out)
        return trades

    def _report(self, trades, duration, trades_out=None):
        print("\n" + "=" * 60)
        print(f"BACKTEST COMPLETE in {duration:.1f}s | {len(trades)} trades taken")
        print("=" * 60)

        def line(name, m):
            print(f"\n[{name}]")
            print(f"  trades={m['trades']}  win%={m['win_rate']*100:.1f}  "
                  f"expectancy={m['expectancy']:+.2f}R  totalR={m['total_r']:+.2f}")
            pf = m['profit_factor']
            pf_str = "inf" if pf == float('inf') else f"{pf:.2f}"
            print(f"  PF={pf_str}  maxDD={m['max_drawdown_r']:.2f}R  "
                  f"avgW={m['avg_win']:+.2f}R avgL={m['avg_loss']:+.2f}R  "
                  f"streak={m['max_losing_streak']}  expired={m['expired']} open={m['open_at_end']}")

        by_strat = {}
        for t in trades:
            by_strat.setdefault(t['strat'], []).append(t)
        for name in sorted(by_strat):
            line(name, aggregate_metrics(by_strat[name]))
        line("COMBINED", aggregate_metrics(trades))

        if trades_out:
            import csv
            keys = ['time', 'strat', 'dir', 'cmd', 'entry', 'sl', 'tp',
                    'outcome', 'r', 'bar_idx', 'fill_offset', 'exit_offset']
            with open(trades_out, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
                w.writeheader()
                for t in trades:
                    w.writerow(t)
            print(f"\n[CSV] wrote {len(trades)} trades -> {trades_out}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Signal-edge PnL backtest (R-multiples).")
    p.add_argument("--csv", default=None, help="path to OHLC CSV (default: auto-discover)")
    p.add_argument("--shift", type=int, default=-7, help="hours to shift broker time toward NY")
    p.add_argument("--trades-out", default=None, help="optional path to write a per-trade CSV")
    a = p.parse_args()

    target = a.csv
    if not target:
        for c in ["test_data.csv", "../../test_data.csv", "data/history/EURUSD_M5.csv"]:
            if os.path.exists(c):
                target = c
                break
    if not target:
        print("❌ No CSV found. Pass --csv <path>.")
        sys.exit(1)

    engine = Backtester(target, shift_hours=a.shift)
    asyncio.run(engine.run(trades_out=a.trades_out))