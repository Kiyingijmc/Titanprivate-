# ==============================================================================
# FILE: src/core/candle_maker.py
# TYPE: PERFORMANCE UPDATE (Memory & Caching)
# AUDIT: 
#   1. Implemented DataFrame Caching (Eliminates rebuild overhead on reads).
#   2. Retained O(1) Deque storage for fast appends.
#   3. Preserved Year 3000/Millisecond logic from v14.1 spec.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
from datetime import datetime, timezone
from collections import deque

class CandleMaker:
    """
    Titan v14.3 Optimized Candle Engine.
    
    AUDIT UPGRADE:
    - Retains 100% of v14.1 logic structure.
    - Adds 'Dirty Cache' mechanism to prevent redundant DataFrame reconstruction
      when multiple strategies access the same history.
    """
    def __init__(self, timeframe_minutes=5):
        self.tf_min = timeframe_minutes
        self.current_candle = None
        
        # v14.1 defined a 500 bar history limit
        self.history_limit = 500
        self.history_deque = deque(maxlen=self.history_limit)
        
        # AUDIT FIX: Caching Mechanism
        self._cached_df = None
        self._is_dirty = True
        
        # Pre-initialize the empty DataFrame structure
        self._init_types()

    def _init_types(self):
        """Restores the explicit v14.1 casting to prevent analysis errors."""
        self._empty_frame = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'tick_volume'])
        self._empty_frame = self._empty_frame.astype({
            'open': 'float64', 
            'high': 'float64', 
            'low': 'float64', 
            'close': 'float64', 
            'tick_volume': 'int64'
        })
        # Set cache to empty initially
        self._cached_df = self._empty_frame.copy()
        self._is_dirty = False

    @property
    def candles(self):
        """
        Accessor with Cache Logic.
        Allows external modules (DataStore/SMC) to access .candles as a DataFrame
        without incurring construction penalties on every read.
        """
        if not self.history_deque:
            return self._empty_frame.copy()
            
        # Return cached version if nothing has changed
        if not self._is_dirty and self._cached_df is not None:
            return self._cached_df

        # Rebuild Cache
        df = pd.DataFrame(list(self.history_deque))
        
        # Ensure type safety and index resetting exactly as v14.1 expected
        self._cached_df = df.astype({
            'open': 'float64', 'high': 'float64', 
            'low': 'float64', 'close': 'float64', 
            'tick_volume': 'int64'
        }).reset_index(drop=True)
        
        self._is_dirty = False
        return self._cached_df

    @candles.setter
    def candles(self, df):
        """
        Allows DataStore.ingest_history to bulk-load data.
        Invalidates cache upon load.
        """
        if df is None or df.empty:
            return
            
        # Handle v14.1 naming variations
        if 'tick_volume' not in df.columns and 'tickvol' in df.columns:
            df = df.rename(columns={'tickvol': 'tick_volume'})
            
        self.history_deque.clear()
        
        # Convert records and populate the deque
        records = df.to_dict('records')
        for rec in records:
            self.history_deque.append(rec)
            
        # Flag cache as dirty so next read rebuilds it
        self._is_dirty = True

    def process_tick(self, tick_data):
        """
        Processes inbound ticks. 
        RETAINS: v14.1 Millisecond Handling, OHLCV logic, and Bucket Flooring.
        """
        price = float(tick_data['b']) # Bid Price
        raw_time = tick_data['t']
        
        # --- RESTORED v14.1 CRASH FIX: HANDLE MILLISECONDS ---
        # Stamp as naive UTC (matches DataStore.ingest_history's
        # pd.to_datetime(..., unit='s')) so live and history bars share one
        # clock; datetime.fromtimestamp() alone would use local time and
        # split the buffer's epoch by the host's UTC offset.
        if raw_time > 32503680000: # Year 3000 in seconds
            ts = datetime.fromtimestamp(raw_time / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        else:
            ts = datetime.fromtimestamp(raw_time, tz=timezone.utc).replace(tzinfo=None)
        
        # Determine Minute Bucket (v14.1 Logic)
        minute_floored = (ts.minute // self.tf_min) * self.tf_min
        bucket_time = ts.replace(minute=minute_floored, second=0, microsecond=0)

        # 1. Initialize First Candle
        if self.current_candle is None:
            self._start_new_candle(bucket_time, price)
            return None

        # 2. Check Time Logic (Candle Close)
        if bucket_time > self.current_candle['time']:
            # CANDLE CLOSED: Push to historical deque
            self.history_deque.append(self.current_candle.copy())
            self._is_dirty = True # Mark for rebuild
            
            # Start New
            self._start_new_candle(bucket_time, price)
            
            # Return Formatted DataFrame for the Strategy Pulse
            # This triggers a rebuild of the cache, ensuring up-to-date data
            return self.candles

        # 3. Update Metrics (v14.1 Logic)
        if price > self.current_candle['high']: self.current_candle['high'] = price
        if price < self.current_candle['low']:  self.current_candle['low'] = price
        self.current_candle['close'] = price
        self.current_candle['tick_volume'] += 1
        
        return None

    def _start_new_candle(self, time, price):
        """v14.1 Dictionary Initialization."""
        self.current_candle = {
            'time': time,
            'open': price, 'high': price, 'low': price, 'close': price,
            'tick_volume': 1
        }

    def get_history(self):
        """v14.1 Legacy Helper."""
        return self.candles