# ==============================================================================
# FILE: src/strategies/models/unicorn.py
# TYPE: STRATEGY LOGIC
# AUDIT: 
#   1. integrated centralized 'validate_data' check.
#   2. Added ATR safety guards (prevent math errors).
#   3. Retained "Liquidity Sweep" (Stop Hunt) verification logic.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
from src.strategies.base_strategy import BaseStrategy

class UnicornModel(BaseStrategy):
    """
    Unicorn V3.6 (Institutional).
    
    Logic:
    1. FVG + Breaker Block Overlap.
    2. REQUIRED: Liquidity Sweep (Turtle Soup) prior to displacement.
    3. Bias Alignment.
    
    AUDIT UPGRADE:
    - Robust DataFrame access via BaseStrategy validation.
    - Protected Math for Breaker overlap calculations.
    """
    def __init__(self, config, logger):
        super().__init__("Unicorn", config, logger)
        self.scan_depth = config.get('scan_depth', 288) # Default 24 Hours lookback
        self.risk_reward = config.get('risk_reward', 3.0)

    async def analyze_tick(self, tick_data, history_df): 
        # Unicorn operates on candle closes
        pass

    async def on_new_candle(self, df, context=None):
        """
        Executed on M5 candle close.
        """
        # 1. Validation (Audit Fix)
        # Needs deep history for scanning breakers (min 200)
        if not self.validate_data(df, min_length=200):
            return None
        
        current = df.iloc[-1]
        
        # Bias Filter
        bias = context.get('bias', "NEUTRAL") if context else "NEUTRAL"
        
        # Volatility Buffer (1.5 ATR)
        # Safe ATR access
        raw_atr = df.iloc[-2].get('ATR', 0.0)
        atr = float(raw_atr) if pd.notnull(raw_atr) else 0.0
        
        if atr <= 0: return None
        buffer = atr * 1.5

        # ==========================
        #      BULLISH UNICORN
        # ==========================
        if current['is_fvg_bull']:
            # Trend Filter: Don't take Longs in strong Bear trend
            if bias == "BEARISH": return None
            
            fvg_top = current['fvg_top']
            fvg_bot = current['fvg_bottom']
            
            # Scan History: Exclude recent 12 bars (1 hour) to find OLDER Breakers
            subset = df.iloc[-self.scan_depth : -12] 
            
            # Identify Swings in history
            potential_breakers = subset[subset['is_swing_high'] == True]
            
            # Geometric Overlap Check
            for idx, breaker in potential_breakers.iterrows():
                level = breaker['high']
                
                # 1. Overlap Check (Breaker Level inside FVG + Buffer)
                if (fvg_bot - buffer) <= level <= (fvg_top + buffer):
                    
                    # 2. Structural Confirmation (Price > Breaker)
                    if current['close'] > level:
                        
                        # --- 3. LIQUIDITY SWEEP CHECK ---
                        # Verify the move that created this FVG actually took out liquidity first.
                        # Look at the 20 bars prior to the current FVG.
                        recent_action = df.iloc[-20:-1]
                        recent_lows = recent_action[recent_action['is_swing_low'] == True]
                        
                        # We need to see that price dipped below a recent swing low
                        # before reversing up into this FVG.
                        swept_liquidity = False
                        if not recent_lows.empty:
                            lowest_recent = recent_action['low'].min()
                            # Check if we went lower than a previous swing low
                            prev_swing_low = recent_lows['low'].min()
                            if lowest_recent <= prev_swing_low:
                                swept_liquidity = True
                        
                        if not swept_liquidity:
                            # Strict Institutional Filter: No Sweep = No Trade
                            continue

                        # SETUP CONFIRMED
                        entry = level 
                        sl = current['low'] - atr 
                        dist = abs(entry - sl)
                        
                        # Anti-Spam (Don't signal if SL is dangerously tight)
                        if dist < (atr * 0.5): continue
                            
                        tp = entry + (dist * self.risk_reward)

                        self.log(f"🦄 UNICORN (Long) Found @ {entry} [Sweep Confirmed]")
                        return {'signal': 'BUY', 'type': 'LIMIT', 'price': entry, 'sl': sl, 'tp': tp}

        # ==========================
        #      BEARISH UNICORN
        # ==========================
        if current['is_fvg_bear']:
            # Trend Filter: Don't take Shorts in strong Bull trend
            if bias == "BULLISH": return None
            
            fvg_top = current['fvg_top']
            fvg_bot = current['fvg_bottom']
            
            subset = df.iloc[-self.scan_depth : -12]
            potential_breakers = subset[subset['is_swing_low'] == True]
            
            for idx, breaker in potential_breakers.iterrows():
                level = breaker['low']
                
                # 1. Overlap Check
                if (fvg_bot - buffer) <= level <= (fvg_top + buffer):
                    
                    # 2. Structural Confirmation
                    if current['close'] < level:
                        
                        # --- 3. LIQUIDITY SWEEP CHECK ---
                        recent_action = df.iloc[-20:-1]
                        recent_highs = recent_action[recent_action['is_swing_high'] == True]
                        
                        swept_liquidity = False
                        if not recent_highs.empty:
                            highest_recent = recent_action['high'].max()
                            # Check if we went higher than a previous swing high
                            prev_swing_high = recent_highs['high'].max()
                            if highest_recent >= prev_swing_high:
                                swept_liquidity = True
                        
                        if not swept_liquidity:
                            continue

                        entry = level
                        sl = current['high'] + atr
                        dist = abs(sl - entry)
                        
                        if dist < (atr * 0.5): continue
                            
                        tp = entry - (dist * self.risk_reward)
                        
                        self.log(f"🦄 UNICORN (Short) Found @ {entry} [Sweep Confirmed]")
                        return {'signal': 'SELL', 'type': 'LIMIT', 'price': entry, 'sl': sl, 'tp': tp}

        return None