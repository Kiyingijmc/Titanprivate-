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

    async def run(self):
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
                    price = decision['price']
                    
                    if strat.name != "CRT":
                        if (htf_bias == "BULLISH" and sig_type == "SELL") or \
                           (htf_bias == "BEARISH" and sig_type == "BUY"):
                               continue
                    
                    signals.append({
                        'time': current_time,
                        'strat': strat.name,
                        'type': sig_type,
                        'price': price,
                        'bias_confluence': (sig_type == "BUY" and htf_bias=="BULLISH") or (sig_type == "SELL" and htf_bias=="BEARISH")
                    })

        duration = time.time() - start_time
        self._print_results(signals, duration)

    def _print_results(self, signals, duration):
        print("\n" + "="*50)
        print(f"SIMULATION COMPLETE in {duration:.2f}s")
        print(f"TRADES GENERATED: {len(signals)}")
        print("="*50)
        
        tally = {}
        for s in signals:
            name = s['strat']
            tally[name] = tally.get(name, 0) + 1
        
        for name, count in tally.items():
            print(f" - {name}: {count}")
            
        confluence_trades = len([s for s in signals if s['bias_confluence']])
        pct = int(confluence_trades/len(signals)*100) if signals else 0
        print(f"\nContext Alignment: {confluence_trades}/{len(signals)} ({pct}%)")

if __name__ == "__main__":
    target = None
    candidates = ["test_data.csv", "../../test_data.csv", "data/history/EURUSD_M5.csv"]
    
    for c in candidates:
        if os.path.exists(c):
            target = c
            break
            
    if target:
        bt = Backtester(target, shift_hours=-7)
        asyncio.run(bt.run())
    else:
        print("❌ 'test_data.csv' not found. Place a CSV in the folder.")