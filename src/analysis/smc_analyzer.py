import pandas as pd
import numpy as np

class SMCAnalyzer:
    """
    Version 14.1 Production SMC Engine.
    Restores oper.txt Displacement Logic + V14 Stability Padding.
    """
    def __init__(self, df: pd.DataFrame):
        # Work on deep copy to prevent slice warnings (oper.txt logic)
        self.df = df.copy()
        
        # 1. RESTORED: Defensive Initialization (Prevents KeyErrors in strategies)
        defaults = {
            'is_swing_high': False, 'is_swing_low': False,
            'is_fvg_bull': False, 'is_fvg_bear': False,
            'fvg_top': 0.0, 'fvg_bottom': 0.0, 'ATR': 0.0
        }
        for col, val in defaults.items():
            if col not in self.df.columns:
                self.df[col] = val

    def process(self):
        """Runs institutional detection with stability guards."""
        # V14 Audit Fix: Increased minimum bar count for indicator stability
        if len(self.df) < 50: 
            return self.df
        
        try:
            self._calculate_atr()
            self._identify_fractals()
            self._detect_fvg()
            
            # V14 Audit Fix: Stability Guard / Cold-Start Protection
            # Nullify the first 50 bars so strategies don't trade "unsettled" ATR math
            self.df.iloc[:50, self.df.columns.get_loc('is_fvg_bull')] = False
            self.df.iloc[:50, self.df.columns.get_loc('is_fvg_bear')] = False
            
        except Exception as e:
            print(f"[SMC ERROR] Calculation failed: {e}")
            return self.df
            
        return self.df

    def _calculate_atr(self, period=14):
        """Precise Volatility calculation from oper.txt"""
        high_low = self.df['high'] - self.df['low']
        high_close = np.abs(self.df['high'] - self.df['close'].shift())
        low_close = np.abs(self.df['low'] - self.df['close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        self.df['ATR'] = true_range.rolling(period).mean()

    def _identify_fractals(self):
        """Restored exact 5-Bar Fractal Detection from oper.txt"""
        highs = self.df['high'].values
        lows = self.df['low'].values
        
        h_idx = self.df.columns.get_loc('is_swing_high')
        l_idx = self.df.columns.get_loc('is_swing_low')

        for i in range(2, len(self.df) - 2):
            # Swing High
            if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
                highs[i] > highs[i+1] and highs[i] > highs[i+2]):
                self.df.iat[i, h_idx] = True

            # Swing Low
            if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
                lows[i] < lows[i+1] and lows[i] < lows[i+2]):
                self.df.iat[i, l_idx] = True

    def _detect_fvg(self):
        """
        Restored FULL FVG with Displacement Filter (oper.txt).
        Requires Candle Body > 1.0 * ATR to confirm Institutional Momentum.
        """
        highs = self.df['high'].values
        lows = self.df['low'].values
        opens = self.df['open'].values
        closes = self.df['close'].values
        atrs = self.df['ATR'].fillna(0.0001).values
        
        fvg_bull_idx = self.df.columns.get_loc('is_fvg_bull')
        fvg_bear_idx = self.df.columns.get_loc('is_fvg_bear')
        top_idx = self.df.columns.get_loc('fvg_top')
        bot_idx = self.df.columns.get_loc('fvg_bottom')

        for i in range(2, len(self.df)):
            # Displacement Logic (Restored from oper.txt)
            body_size = abs(closes[i] - opens[i])
            min_displacement = atrs[i] * 1.0 
            
            # Skip if the move isn't "Institutional" (Too quiet)
            if body_size < min_displacement: 
                continue

            # Bearish FVG (Gap Down)
            if lows[i-2] > highs[i]:
                self.df.iat[i, fvg_bear_idx] = True
                self.df.iat[i, top_idx] = lows[i-2]
                self.df.iat[i, bot_idx] = highs[i]

            # Bullish FVG (Gap Up)
            if highs[i-2] < lows[i]:
                self.df.iat[i, fvg_bull_idx] = True
                self.df.iat[i, top_idx] = lows[i]
                self.df.iat[i, bot_idx] = highs[i-2]

    @staticmethod
    def is_mitigated(fvg_top, fvg_bot, future_candles, type="BULL"):
        """Restored Gap Mitigation Checker from oper.txt"""
        if future_candles.empty: 
            return False
        
        if type == "BULL":
            # If any future candle low dips into/below the bullish FVG
            mitigation = future_candles[future_candles['low'] <= fvg_top]
        else:
            # If any future candle high spikes into/above the bearish FVG
            mitigation = future_candles[future_candles['high'] >= fvg_bot]
            
        return not mitigation.empty