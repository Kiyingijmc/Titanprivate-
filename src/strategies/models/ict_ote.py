# ==============================================================================
# FILE: src/strategies/models/ict_ote.py
# TYPE: STRATEGY LOGIC
# AUDIT: 
#   1. Integrated centralized 'validate_data' check.
#   2. Added ATR safety guards.
#   3. Retained Fibonacci OTE (0.705) + FVG Confluence logic.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
from src.strategies.base_strategy import BaseStrategy

class ICT_OTE(BaseStrategy):
    """
    ICT OTE V3 (Production).
    Optimal Trade Entry using Fibonacci and FVG Confluence.
    
    Logic:
    1. Identify direction via FVG (e.g. Bullish FVG = Buy Bias).
    2. Find the impulse leg (Significant Swing > 2 ATR).
    3. Place Limit at 70.5% (OTE) Retracement of that leg.
    4. Confirm Limit level is inside/near the FVG.
    """
    def __init__(self, config, logger):
        super().__init__("ICT_OTE", config, logger)
        self.ote_level = config.get('ote_level', 0.705)
        self.min_swing_atr = config.get('min_swing_atr', 2.0)
        self.last_signal_time = None

    async def analyze_tick(self, tick_data, history_df): 
        # Low frequency logic
        pass

    async def on_new_candle(self, df, context=None):
        """
        Executed on M5 candle close.
        """
        # 1. Validation (Audit Fix)
        if not self.validate_data(df, min_length=50):
            return None
            
        current = df.iloc[-1]
        current_time = current['time']
        
        # Anti-Spam: One signal per candle max
        if self.last_signal_time == current_time: 
            return None

        # Safe ATR Access
        raw_atr = current.get('ATR', 0.0)
        atr = float(raw_atr) if pd.notnull(raw_atr) else 0.0
        if atr <= 0: return None

        # ==========================
        #        BUY LOGIC
        # ==========================
        if current['is_fvg_bull']:
            # Find a SIGNIFICANT Swing Low (Depth Check)
            # Look at recent 50 bars, excluding current
            subset = df.iloc[-50:-1]
            swing_lows = subset[subset['is_swing_low'] == True]
            
            valid_swing = None
            # Scan backwards (newest to oldest) for the first swing deep enough 
            # Depth: Impulse move must be > 2 * ATR height
            for idx in range(len(swing_lows)-1, -1, -1):
                s = swing_lows.iloc[idx]
                height_diff = current['high'] - s['low']
                
                if height_diff > (atr * self.min_swing_atr):
                    valid_swing = s
                    break
            
            if valid_swing is not None:
                leg_low = valid_swing['low']
                leg_high = current['high']
                range_p = leg_high - leg_low
                
                # OTE Calculation (Entry at discount)
                limit_entry = leg_low + (range_p * (1 - self.ote_level))
                
                # Confluence: Overlap Check
                # Is the OTE price "inside or near" the FVG?
                fvg_top = current['fvg_top']
                fvg_bot = current['fvg_bottom']
                
                # Buffer FVG top slightly (0.2 ATR) to catch entries just tapping it
                if fvg_bot <= limit_entry <= (fvg_top + atr*0.2):
                    sl = leg_low # Stop at origin of move
                    dist = abs(limit_entry - sl)
                    
                    if dist < (atr * 0.2): return None # Spread filter
                    
                    tp = limit_entry + (dist * 2.5) # 2.5R Target
                    
                    self.last_signal_time = current_time
                    self.log(f"🦅 OTE (Buy) @ {limit_entry} [Confluence found]")
                    return {'signal': 'BUY', 'type': 'LIMIT', 'price': limit_entry, 'sl': sl, 'tp': tp}

        # ==========================
        #       SELL LOGIC
        # ==========================
        if current['is_fvg_bear']:
            subset = df.iloc[-50:-1]
            swing_highs = subset[subset['is_swing_high'] == True]
            
            valid_swing = None
            for idx in range(len(swing_highs)-1, -1, -1):
                s = swing_highs.iloc[idx]
                height_diff = s['high'] - current['low']
                
                if height_diff > (atr * self.min_swing_atr):
                    valid_swing = s
                    break

            if valid_swing is not None:
                leg_high = valid_swing['high']
                leg_low = current['low']
                range_p = leg_high - leg_low
                
                # OTE Calculation (Entry at premium)
                limit_entry = leg_low + (range_p * self.ote_level)
                
                fvg_top = current['fvg_top']
                fvg_bot = current['fvg_bottom']
                
                # Buffer FVG bottom slightly