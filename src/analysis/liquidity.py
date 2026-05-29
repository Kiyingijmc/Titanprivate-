# ==============================================================================
# FILE: src/analysis/liquidity.py
# TYPE: LOGIC REFINEMENT (Analysis)
# AUDIT: 
#   1. Added Data Copying for isolation.
#   2. Validated numeric inputs for High/Low calculations.
#   3. Retained Institutional PD Array (Premium/Discount) logic.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
import numpy as np

class LiquidityEngine:
    """
    Titan Institutional Liquidity Mapper.
    Identifies Premium/Discount zones (PD Arrays) for Bias determination.
    """
    def __init__(self, history_df):
        # AUDIT: Use copy to prevent reference mutation issues
        self.df = history_df.copy() if history_df is not None else pd.DataFrame()

    def get_pd_arrays(self):
        """
        Identify Premium/Discount Arrays (Highs, Lows, Equilibrium).
        Returns dictionary of key levels.
        """
        # Safety Check: Need enough history
        if self.df.empty or len(self.df) < 50: 
            return {}

        try:
            # 1. Identify the Trading Range (Lookback ~4 days approx for H1)
            # 4 days * 24 bars = ~100 bars
            recent_data = self.df.iloc[-100:]
            
            # Ensure columns are numeric to prevent TypeErrors
            if not np.issubdtype(recent_data['high'].dtype, np.number) or \
               not np.issubdtype(recent_data['low'].dtype, np.number):
                return {}
            
            range_high = recent_data['high'].max()
            range_low = recent_data['low'].min()
            
            # Guard against flatline data (High == Low)
            if range_high == range_low:
                return {}
            
            # 2. Calculate Equilibrium (50% Retracement)
            equilibrium = (range_high + range_low) / 2
            
            # 3. Determine Current Status
            current_price = float(self.df.iloc[-1]['close'])
            
            # Institutional Logic:
            # Price > EQ = PREMIUM (Look for Shorts)
            # Price < EQ = DISCOUNT (Look for Longs)
            status = "PREMIUM" if current_price > equilibrium else "DISCOUNT"
            
            return {
                "PDH": float(range_high),
                "PDL": float(range_low),
                "EQ": float(equilibrium),
                "STATUS": status
            }

        except Exception as e:
            # Return empty if calculation fails preventing BiasEngine crash
            # print(f"[LIQ ERROR] {e}") 
            return {}