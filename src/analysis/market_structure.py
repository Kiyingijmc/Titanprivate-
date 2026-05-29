# ==============================================================================
# FILE: src/analysis/market_structure.py
# TYPE: CRITICAL UPDATE (Performance Optimization)
# AUDIT: Replaced slow iterative loops with Vectorized NumPy/Pandas operations.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
import numpy as np

class MarketStructure:
    def __init__(self, df: pd.DataFrame):
        """
        Expects a DataFrame with columns: ['time', 'open', 'high', 'low', 'close', 'tick_volume']
        """
        # Work on a copy to ensure data integrity and prevent SettingWithCopy warnings
        self.df = df.copy() 
    
    def calculate_atr(self, period=14):
        """
        Standard Average True Range for Displacement logic.
        Vectorized by default in Pandas.
        """
        if 'high' not in self.df.columns or 'low' not in self.df.columns: 
            return self.df

        # Calculate True Range components using vectorized operations
        high_low = self.df['high'] - self.df['low']
        
        # Use simple shift for Previous Close (Vectorized)
        prev_close = self.df['close'].shift()
        
        # Use abs for gaps
        high_close = np.abs(self.df['high'] - prev_close)
        low_close = np.abs(self.df['low'] - prev_close)
        
        # Concatenate and find max along the row axis
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        
        # Add to internal dataframe (Rolling Mean is C-optimized in Pandas)
        self.df['ATR'] = true_range.rolling(period).mean()
        return self.df

    def identify_swings(self, left_bars=3, right_bars=3):
        """
        Fractal Recognition (Swings).
        
        AUDIT FIX:
        Replaced manual Python iteration loops (O(N*M)) with 
        vectorized Rolling Window comparison (O(N)).
        
        Updates self.df with 'is_swing_high' and 'is_swing_low'.
        """
        # Ensure boolean columns exist initialized to False
        self.df['is_swing_high'] = False
        self.df['is_swing_low'] = False

        if len(self.df) < (left_bars + right_bars + 1):
            return self.df

        # --- Vectorized Implementation ---

        # 1. SWING HIGHS
        # A bar is a swing high if it is the Maximum of the window [i-left : i+right]
        # logic: The window size is left + 1 + right
        # We assume the swing point is in the center of the window if left==right.
        # But to match 'left' and 'right' strictly, we use two checks.

        highs = self.df['high']
        
        # Check Left Side: Rolling Max of (left_bars + 1) looking backward
        # Shifted so the current bar is compared to previous 'left' bars
        # Note: We check if rolling_max == current_high
        
        # Logic: High must be greater than left neighbors
        # We construct a window covering [i-left, i]
        roll_left_max_h = highs.rolling(window=left_bars+1, closed='right').max()
        
        # Check Right Side: We look forward. 
        # In Pandas rolling, we can't easily look forward without shifting the result BACK.
        # Window covering [i, i+right]
        # We calculate rolling max of size (right+1) on shifted series (future)
        # Shift highs backwards by 'right_bars' so future comes into current view? 
        # Easier approach: rolling max centered, then check index logic.
        
        # PREFERRED VECTORIZED APPROACH: 
        # Concat shifted series to compare all neighbors at once. 
        # This is strictly equivalent to the Loop logic and extremely fast.
        
        shift_cols_h = []
        shift_cols_l = []

        # Generate neighbor columns
        for i in range(1, left_bars + 1):
            shift_cols_h.append(highs.shift(i)) # Previous bars (i-1, i-2...)
            shift_cols_l.append(self.df['low'].shift(i))
            
        for i in range(1, right_bars + 1):
            shift_cols_h.append(highs.shift(-i)) # Future bars (i+1, i+2...)
            shift_cols_l.append(self.df['low'].shift(-i))

        # Convert list of Series to DataFrame for vectorized comparison
        neighbors_h = pd.concat(shift_cols_h, axis=1)
        neighbors_l = pd.concat(shift_cols_l, axis=1)

        # Vectorized Comparison
        # Check if current 'high' is strictly greater than all neighbors
        # (Using .max(axis=1) across neighbors)
        # Note: Original loop logic allowed equal highs to NOT be a swing if neighbors > current. 
        # But if current == neighbor, the original logic "break" would trigger if neighbor > current.
        # If neighbor == current, it kept is_high=True?
        # Re-reading original: "if highs[i-l] > current_high: is_high = False".
        # So Equal is Allowed. Strict check is only for Greater.
        
        # Swing High Logic
        max_neighbors_h = neighbors_h.max(axis=1)
        # If neighbors are NaN (edges), the result handles implicitly, but we enforce edge buffer later.
        is_swing_h = highs > max_neighbors_h # Strictly High? No, original was ">" failure.
        # If Highs > Max_Neighbor, then it is strictly highest.
        # Original: if neighbor > current, fail. So current >= neighbor is pass.
        
        is_swing_h = highs >= max_neighbors_h # Original logic allowed equals, this retains it.

        # Swing Low Logic
        # Original: if neighbor < current, fail. So current <= neighbor is pass.
        min_neighbors_l = neighbors_l.min(axis=1)
        is_swing_l = self.df['low'] <= min_neighbors_l

        # Apply to DataFrame
        self.df['is_swing_high'] = is_swing_h.fillna(False)
        self.df['is_swing_low'] = is_swing_l.fillna(False)

        # Enforce Edge Cleanliness (Original Loop didn't process first 'left' or last 'right')
        # We strictly set those to False to match original behavior exactly.
        self.df.iloc[:left_bars, self.df.columns.get_loc('is_swing_high')] = False
        self.df.iloc[-right_bars:, self.df.columns.get_loc('is_swing_high')] = False
        self.df.iloc[:left_bars, self.df.columns.get_loc('is_swing_low')] = False
        self.df.iloc[-right_bars:, self.df.columns.get_loc('is_swing_low')] = False

        return self.df

    def detect_displacement(self, multiplier=1.5):
        """
        Updates self.df with 'is_displacement' boolean.
        Vectorized operation.
        """
        # Ensure ATR exists
        if 'ATR' not in self.df.columns:
            self.calculate_atr()

        # Calculate Body Size (Vectorized abs diff)
        body_size = np.abs(self.df['close'] - self.df['open'])
        
        # Check Displacement Condition (Vectorized boolean mask)
        # Using fillna(0) for ATR to prevent errors on first few bars
        threshold = self.df['ATR'].fillna(0) * multiplier
        
        self.df['is_displacement'] = body_size > threshold
        self.df['body_size'] = body_size # Store for debug/telemetry if needed
        
        return self.df

    def get_market_bias(self):
        """
        Returns 1 (Bull), -1 (Bear), 0 (Range) based on structure.
        """
        # Ensure Swings are calculated
        if 'is_swing_high' not in self.df.columns:
            self.identify_swings()
            
        # Get indices of swings
        # Boolean indexing is faster than querying df
        swing_h_indices = np.where(self.df['is_swing_high'])[0]
        swing_l_indices = np.where(self.df['is_swing_low'])[0]
        
        # Need at least 2 highs and 2 lows to determine HH/HL/LH/LL structure
        if len(swing_h_indices) < 2 or len(swing_l_indices) < 2:
            return 0
        
        # Get values (iloc equivalent using numpy direct access for speed)
        # Last swing
        curr_high_idx = swing_h_indices[-1]
        prev_high_idx = swing_h_indices[-2]
        
        curr_low_idx = swing_l_indices[-1]
        prev_low_idx = swing_l_indices[-2]
        
        curr_high = self.df['high'].iat[curr_high_idx]
        prev_high = self.df['high'].iat[prev_high_idx]
        
        curr_low = self.df['low'].iat[curr_low_idx]
        prev_low = self.df['low'].iat[prev_low_idx]
        
        # Structure Analysis
        is_hh = curr_high > prev_high
        is_hl = curr_low > prev_low
        is_lh = curr_high < prev_high
        is_ll = curr_low < prev_low
        
        # Bullish: Higher High + Higher Low
        if is_hh and is_hl:
            return 1
            
        # Bearish: Lower High + Lower Low
        if is_lh and is_ll:
            return -1
            
        # Neutral/Expansion/Compression
        return 0