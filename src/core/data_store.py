# ==============================================================================
# FILE: src/core/data_store.py
# TYPE: STABILITY UPDATE (Data Integrity)
# AUDIT: 
#   1. Fixed duplicate function definition (Source Code Cleanup).
#   2. Added Schema Validation for ZMQ payloads to prevent crashes.
#   3. Standardized Type Casting (String -> Float) for broker feeds.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
from src.core.candle_maker import CandleMaker

class MultiTimeframeStore:
    """
    Central Data Repository for a specific Symbol.
    Manages CandleMakers for M5 and H1 timeframes.
    
    AUDIT FIX:
    - Merged duplicate 'ingest_history' methods from original source.
    - Added input validation for ZMQ data packets.
    """
    def __init__(self, symbol):
        self.symbol = symbol
        self.timeframes = {
            "M5": CandleMaker(5),
            "H1": CandleMaker(60)
        }
        self.history_loaded = False
        
        # MEMORY: Track last processed candle timestamp to prevent 
        # duplicate signals if the broker sends redundant ticks.
        self.last_processed_candle = {
            "M5": None,
            "H1": None
        }

    def ingest_history(self, tf, data_list):
        """
        Loads historical data sent by MT5.
        
        Merged & Optimized Logic:
        1. Validate Input (List check).
        2. Create DataFrame & Map Columns.
        3. Enforce Numeric Types.
        4. Inject into CandleMaker.
        """
        # 1. Validation
        if not data_list or not isinstance(data_list, list): 
            return
        
        if tf not in self.timeframes:
            return

        try:
            # 2. Load into DataFrame
            df = pd.DataFrame(data_list)
            
            # 3. Map MT5 short-keys to Python long-keys
            # Expected ZMQ keys: t=time, o=open, h=high, l=low, c=close, v/tickvol
            mapping = {'t': 'time', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close'}
            
            # Handle variable volume keys safely
            if 'tv' in df.columns: mapping['tv'] = 'tick_volume'
            elif 'tickvol' in df.columns: mapping['tickvol'] = 'tick_volume'
            elif 'v' in df.columns: mapping['v'] = 'tick_volume'
            
            df.rename(columns=mapping, inplace=True)
            
            # 4. Data Cleaning
            # Ensure mandatory columns exist
            required = ['open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required):
                # If partial data, drop invalid rows or return
                return

            # Convert Time (MT5 sends Unix Seconds)
            # Use 'coerce' to handle any malformed timestamps gracefully
            df['time'] = pd.to_datetime(df['time'], unit='s', errors='coerce')
            
            # Ensure Numeric Types (Prevent object/string types from ZMQ JSON)
            for col in required:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Ensure Tick Volume for SMC (Default to 1 if missing)
            if 'tick_volume' not in df.columns:
                df['tick_volume'] = 1
            else:
                df['tick_volume'] = pd.to_numeric(df['tick_volume'], errors='coerce').fillna(1)

            # 5. Inject into the specific timeframe maker
            self.timeframes[tf].candles = df
            self.history_loaded = True
            
            # Logging (Audit: Standardized Sync Success Message)
            if tf == "M5":
                print(f"✅ [SYNC] {self.symbol} history loaded ({len(df)} bars).")
            
        except Exception as e:
            print(f"❌ [SYNC ERROR] {self.symbol} Ingest Failed: {e}")

    def process_tick(self, tick_msg):
        """
        Updates candles with real-time ticks.
        Returns a list of newly closed candles (DataFrame) if a close occurred.
        """
        results = []
        # tick_msg comes as dict e.g. {'s': 'EURUSD', 'b': 1.0500, 't': 123456789}
        
        for tf_name, maker in self.timeframes.items():
            # CandleMaker.process_tick returns None OR a DataFrame (if closed)
            res_df = maker.process_tick(tick_msg)
            
            if res_df is not None and not res_df.empty:
                # --- DUPLICATE FILTER ---
                # Check the time of the newly closed candle
                # Use iloc[-1] because candle maker returns the full history
                current_time = res_df.iloc[-1]['time']
                
                # Check if we already processed this exact candle timestamp for this TF
                if self.last_processed_candle[tf_name] != current_time:
                    # New candle confirmed
                    self.last_processed_candle[tf_name] = current_time
                    results.append((tf_name, res_df))
                # Else: We already processed this candle, ignore duplicate trigger
                
        return results

    def get_data(self, tf):
        """Accessor for analysis engines."""
        if tf in self.timeframes:
            return self.timeframes[tf].get_history()
        return pd.DataFrame()