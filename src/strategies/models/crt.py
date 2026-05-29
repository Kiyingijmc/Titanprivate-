# ==============================================================================
# FILE: src/strategies/models/crt.py
# TYPE: STRATEGY LOGIC
# AUDIT: 
#   1. Integrated centralized 'validate_data' check.
#   2. Robust "Previous Day" calculation (Handles empty history safety).
#   3. Added ATR guards and Config parsing safety.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
from src.strategies.base_strategy import BaseStrategy

class CandleRangeTheory(BaseStrategy):
    """
    CRT V3.3 (Professional Grade).
    Features:
    - Session Time Filter (Asian Kill).
    - Robust Date Calculation (Handles Weekend/Holiday gaps).
    - Dynamic ATR Padding.
    - Trend Filter (Bias).
    """
    def __init__(self, config, logger):
        super().__init__("CRT", config, logger)
        self.pdh = 0.0
        self.pdl = 0.0
        self.last_day_calc = -1
        
        # Config Safety
        self.use_filter = config.get('trend_filter', True)
        
        # Handle Active Hours Config (can be list of ints or strings)
        hours = config.get('active_hours', [2, 17])
        try:
            self.start_hour = int(hours[0])
            self.end_hour = int(hours[1])
        except (ValueError, IndexError):
            self.start_hour = 2
            self.end_hour = 17

    async def analyze_tick(self, tick_data, history_df): 
        # CRT operates on candle close
        pass

    async def on_new_candle(self, df, context=None):
        """
        Executed on M5 candle close.
        """
        # 1. Validation (Audit Fix)
        # Needs decent history to find Previous Day levels
        if not self.validate_data(df, min_length=50, check_smc=False):
            return None
        
        current_candle = df.iloc[-1]
        current_time = current_candle['time']
        
        # 2. TIME FILTER: Session Check
        # Example: Trade only between 02:00 and 17:00 Broker Time
        if not (self.start_hour <= current_time.hour < self.end_hour):
            return None

        # 3. DAILY LEVELS RECALCULATION (Robust)
        if current_time.day != self.last_day_calc:
            # We strictly look for the "Previous Day's" data.
            # On Monday, we need Friday. The logic must look back safely.
            current_date = current_time.date()
            
            # Mask: All data strictly before today
            # Use safe accessor to avoid copy warnings if slice
            past_data = df[df['time'].dt.date < current_date]
            
            if not past_data.empty:
                # Identify the date of the very last candle in the past data
                # This automatically handles weekends (e.g. on Mon, last date is Fri)
                last_active_date = past_data.iloc[-1]['time'].date()
                
                # Slice only that specific day
                day_slice = past_data[past_data['time'].dt.date == last_active_date]
                
                if not day_slice.empty:
                    self.pdh = float(day_slice['high'].max())
                    self.pdl = float(day_slice['low'].min())
                    self.last_day_calc = current_time.day
                    # Optional Debug:
                    # self.log(f"CRT Levels Set: High {self.pdh} | Low {self.pdl}")
                else:
                    # Data gap; wait for more history
                    return None
            else:
                # Not enough history loaded to see yesterday
                return None

        # Safety: Levels must be valid
        if self.pdh == 0 or self.pdl == 0: return None
        
        # 4. CONTEXT & MATH
        bias = context.get('bias', "NEUTRAL") if context else "NEUTRAL"
        
        # Dynamic Padding: 20% of Daily ATR (or fallback to candle ATR)
        raw_atr = current_candle.get('ATR', 0.0)
        atr = float(raw_atr) if pd.notnull(raw_atr) and raw_atr > 0 else (current_candle['close'] * 0.001)
        padding = atr * 0.2
        
        # 5. EXECUTION LOGIC
        # SHORT: Sweep PDH + Rejection
        # Logic: High went above PDH, but Close closed below PDH (Wick Rejection)
        if current_candle['high'] > self.pdh and current_candle['close'] < self.pdh:
            # Trend Filter
            if self.use_filter and bias == "BULLISH": return None
            
            entry = current_candle['close']
            # Stop Loss above the wick
            sl = current_candle['high'] + padding
            
            dist = abs(entry - sl)
            if dist < (atr * 0.1): return None # Spread protection
            
            tp = entry - (dist * 3.0) # 3R Target
            
            self.log(f"🕯️ CRT (Short) @ {entry} [PDH Rejection]")
            return {'signal': 'SELL', 'type': 'MARKET', 'price': entry, 'sl': sl, 'tp': tp}
            
        # LONG: Sweep PDL + Rejection
        # Logic: Low went below PDL, but Close closed above PDL
        if current_candle['low'] < self.pdl and current_candle['close'] > self.pdl:
            # Trend Filter
            if self.use_filter and bias == "BEARISH": return None
            
            entry = current_candle['close']
            # Stop Loss below the wick
            sl = current_candle['low'] - padding
            
            dist = abs(entry - sl)
            if dist < (atr * 0.1): return None
            
            tp = entry + (dist * 3.0)
            
            self.log(f"🕯️ CRT (Long) @ {entry} [PDL Rejection]")
            return {'signal': 'BUY', 'type': 'LIMIT', 'price': entry, 'sl': sl, 'tp': tp}

        return None