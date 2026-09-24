# ==============================================================================
# FILE: src/strategies/models/silver_bullet.py
# TYPE: STRATEGY LOGIC
# AUDIT: 
#   1. Integrated centralized 'validate_data' for dataframe safety.
#   2. Added error handling for Time Window configuration parsing.
#   3. Configurable New York windows; current H1 setup allows all hours.
#   4. Reject nonfinite inputs and invalid order geometry.
# ==============================================================================

import math
import pandas as pd
from src.strategies.base_strategy import BaseStrategy

class SilverBullet(BaseStrategy):
    """
    Displacement/FVG limit entries on closed candles.

    Windows use the supplied New York clock; current H1 configuration allows
    all hours. No first-gap-per-session restriction is implemented here.
    """
    def __init__(self, config, logger):
        super().__init__("SilverBullet", config, logger)
        
        # Timing windows (New York hours, end exclusive). Prefer multi-window
        # 'windows'; fall back to the legacy single 'session_ny' window.
        self.windows = self._parse_windows(config)
        self.rr = float(config.get('risk_reward', 2.0))

        # Stop distance in ATR multiples from the ENTRY. The legacy 0.2 buffer
        # made every trade spread-fatal (~1 pip risk on M5); 1.0 ATR on H1 is
        # the historical study config. Execution-sensitive results supersede
        # its profitability claim; see the 2026-09-16 execution diagnostic.
        self.stop_atr = float(config.get('stop_atr', 1.0))
        if not all(math.isfinite(v) and v > 0 for v in (self.rr, self.stop_atr)):
            raise ValueError("SilverBullet risk_reward and stop_atr must be finite and positive")

        # H1 is the v14.4.2 default; M5 remains available via config
        # for research but is cost-dead live.
        self.timeframe = str(config.get('timeframe', 'H1'))

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
        Executed on each closed candle of the configured timeframe.
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
        except (ValueError, IndexError, AttributeError, TypeError):
            return None
            
        # Strict Window Check (e.g. 10 <= Hour < 11)
        if not self._in_window(h_part):
            return None

        # Get latest closed candle
        current = df.iloc[-1]

        # Reject malformed inputs here, before NaN comparisons can bypass
        # momentum checks or produce a non-executable order. Only the selected
        # FVG edge is required: the unused edge may legitimately be absent.
        try:
            o, h, l, c, atr = (float(current[k]) for k in
                               ('open', 'high', 'low', 'close', 'ATR'))
            bull, bear = current['is_fvg_bull'], current['is_fvg_bear']
            if pd.isna(bull) or pd.isna(bear):
                return None
            if bull not in (True, False) or bear not in (True, False):
                return None
            if bool(bull) == bool(bear):
                return None
            entry = float(current['fvg_top' if bull else 'fvg_bottom'])
        except (KeyError, ValueError, TypeError, OverflowError):
            return None
        if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c, atr, entry)):
            return None
        if l > min(o, c) or h < max(o, c):
            return None
        
        # 3. MOMENTUM / DISPLACEMENT VERIFICATION
        # We need a volatile move, not just a quiet FVG.
        
        body_size = abs(c - o)
        
        # Rule: Body must be comparable to the ATR (at least 80% size)
        # This filters out low-volatility drifts
        if body_size < (atr * 0.8): 
            return None 

        # 4. EXECUTION
        # Stop = stop_atr * ATR from the entry (v14.4.2 sizing; the
        # entry sits at the FVG edge, so the legacy candle-extreme formula and
        # entry-anchored formula coincide at stop_atr=0.2).
        # SELL Logic
        if bear:
            sl = entry + (atr * self.stop_atr)
            dist = abs(entry - sl)
            tp = entry - (dist * self.rr)
            if not (all(math.isfinite(v) for v in (sl, tp)) and 0 < tp < entry < sl):
                return None

            self.log(f"🔫 SILVER BULLET (Sell) @ {entry}")
            return {'signal': 'SELL', 'type': 'LIMIT', 'price': entry, 'sl': sl, 'tp': tp}

        # BUY Logic
        if bull:
            sl = entry - (atr * self.stop_atr)
            dist = abs(entry - sl)
            tp = entry + (dist * self.rr)
            if not (all(math.isfinite(v) for v in (sl, tp)) and 0 < sl < entry < tp):
                return None

            self.log(f"🔫 SILVER BULLET (Buy) @ {entry}")
            return {'signal': 'BUY', 'type': 'LIMIT', 'price': entry, 'sl': sl, 'tp': tp}

        return None
