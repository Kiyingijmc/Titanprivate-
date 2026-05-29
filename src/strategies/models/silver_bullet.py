# ==============================================================================
# FILE: src/strategies/models/silver_bullet.py
# TYPE: STRATEGY LOGIC
# AUDIT: 
#   1. Integrated centralized 'validate_data' for dataframe safety.
#   2. Added error handling for Time Window configuration parsing.
#   3. Retained strict 10AM-11AM New York Session logic.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
from src.strategies.base_strategy import BaseStrategy

class SilverBullet(BaseStrategy):
    """
    Silver Bullet V3.1 (Production).
    
    Concept:
    Trading purely on TIME and MOMENTUM.
    During the specific 10 AM (NY) window, macro volatility often injects
    strong displacement. We trade the first strong FVG in this window.
    """
    def __init__(self, config, logger):
        super().__init__("SilverBullet", config, logger)
        
        # Timing windows (broker-time hours, end exclusive). Prefer multi-window
        # 'windows'; fall back to the legacy single 'session_ny' window.
        self.windows = self._parse_windows(config)
        self.rr = config.get('risk_reward', 2.0)

    def _parse_windows(self, config):
        raw = config.get('windows')
        if raw:
            out = []
            for w in raw:
                try:
                    out.append((int(str(w[0]).split(':')[0]), int(str(w[1]).split(':')[0])))
                except (ValueError, IndexError, TypeError):
                    continue
            if out:
                return out
        times = config.get('session_ny', ["10:00", "11:00"])
        try:
            return [(int(str(times[0]).split(':')[0]), int(str(times[1]).split(':')[0]))]
        except (ValueError, IndexError):
            self.logger.log_event("WARN", "STRATEGY", "SilverBullet timing config invalid; default 10-11.")
            return [(10, 11)]

    def _in_window(self, hour):
        return any(start <= hour < end for start, end in self.windows)

    async def analyze_tick(self, tick_data, history_df):
        # Low frequency strategy (Candle close only)
        pass

    async def on_new_candle(self, df, context=None):
        """
        Executed on every M5 candle close.
        """
        # 1. Validation (Audit Update)
        if not self.validate_data(df, min_length=50):
            return None
            
        # 2. TIME GATE
        # Context is required for time-based strategies
        if not context: return None
        
        ny_time_str = context.get('ny_time', "")
        try: 
            # Expecting "HH:MM:SS EST"
            h_part = int(ny_time_str.split(':')[0])
        except (ValueError, IndexError): 
            return None
            
        # Strict Window Check (e.g. 10 <= Hour < 11)
        if not self._in_window(h_part):
            return None

        # Get latest closed candle
        current = df.iloc[-1]
        
        # 3. MOMENTUM / DISPLACEMENT VERIFICATION
        # We need a volatile move, not just a quiet FVG.
        atr = current.get('ATR', 0.0)
        
        # Prevent math errors if ATR is missing/zero (Audit Fix)
        if atr <= 0: return None
            
        body_size = abs(current['close'] - current['open'])
        
        # Rule: Body must be comparable to the ATR (at least 80% size)
        # This filters out low-volatility drifts
        if body_size < (atr * 0.8): 
            return None 

        # 4. EXECUTION
        # SELL Logic
        if current['is_fvg_bear']:
            entry = current['fvg_bottom']
            # Dynamic Stop: High of the displacement candle + small buffer
            sl = current['high'] + (atr * 0.2)
            dist = abs(entry - sl)
            tp = entry - (dist * self.rr)
            
            self.log(f"🔫 SILVER BULLET (Sell) @ {entry}")
            return {'signal': 'SELL', 'type': 'LIMIT', 'price': entry, 'sl': sl, 'tp': tp}

        # BUY Logic
        if current['is_fvg_bull']:
            entry = current['fvg_top']
            sl = current['low'] - (atr * 0.2)
            dist = abs(entry - sl)
            tp = entry + (dist * self.rr)
            
            self.log(f"🔫 SILVER BULLET (Buy) @ {entry}")
            return {'signal': 'BUY', 'type': 'LIMIT', 'price': entry, 'sl': sl, 'tp': tp}

        return None