# ==============================================================================
# FILE: src/risk/correlation.py
# TYPE: RISK LOGIC UPDATE (Math Stability)
# AUDIT: 
#   1. Improved DataFrame alignment logic (handles Crypto vs Forex mismatched times).
#   2. Removed aggressive .dropna() that caused empty matrices on data gaps.
#   3. Added type-safety to prevent correlation of Time/String columns.
# STATUS: PRODUCTION READY
# ==============================================================================

import pandas as pd
import numpy as np
import time

class CorrelationManager:
    """
    Titan Institutional Correlation Filter.
    Blocks trades if a highly correlated pair is already open.
    
    AUDIT UPGRADE:
    - Uses pairwise correlation with NaN tolerance (Pairwise Complete).
    - Prevents data loss when aligning distinct asset classes (e.g. BTC vs EURUSD).
    """
    def __init__(self, data_store):
        # References the SystemController.market_data (MultiTimeframeStore)
        self.store = data_store
        
        # Configuration
        self.threshold = 0.8
        self.matrix = None
        self.last_update = 0
        self.update_interval = 3600 # Cache Matrix for 1 Hour (O(1) access)

    def _update_matrix(self):
        """
        Recalculates correlation matrix from H1 data.
        Optimized to handle misaligned timestamps and gaps.
        """
        now = time.time()
        # Cache Check
        if (now - self.last_update) < self.update_interval and self.matrix is not None:
            return

        try:
            price_series = {}
            valid_symbols = []
            
            # 1. Gather Data Streams
            for sym, store_obj in self.store.items():
                # We use H1 close data for correlation
                df = store_obj.get_data("H1")
                
                # Validation: Need enough data for statistical significance
                if not df.empty and len(df) > 50:
                    # Calculate Returns on the individual series FIRST
                    # This preserves the internal consistency of that asset
                    # pct_change fillna(0) to remove the first NaN
                    returns = df['close'].pct_change()
                    
                    # Store Series with Datetime Index for alignment
                    returns.index = pd.to_datetime(df['time'])
                    
                    # Deduplicate indices to prevent reindexing errors
                    returns = returns[~returns.index.duplicated(keep='last')]
                    
                    price_series[sym] = returns
                    valid_symbols.append(sym)
            
            if len(valid_symbols) < 2: 
                return

            # 2. Merge & Correlate
            # Use concat on axis=1, which automatically aligns indices (outer join)
            full_df = pd.concat(price_series.values(), keys=price_series.keys(), axis=1)
            
            # AUDIT FIX: Do NOT use dropna() on the full frame.
            # Rationale: BTC runs on weekends, EURUSD does not. dropna() would remove
            # ALL weekend data for BTC, and if any gap exists in EURUSD, it drops rows.
            # Pandas .corr() handles NaNs pairwise automatically.
            
            # Restrict to last 100 common periods to keep it responsive but significant
            # Tail logic: Take last N rows regardless of NaNs
            full_df = full_df.tail(100)
            
            if not full_df.empty:
                # min_periods=30 ensures we don't correlate based on just 1-2 overlapping candles
                self.matrix = full_df.corr(min_periods=30)
                self.last_update = now
                # Debug info (optional)
                # print(f"[CORR] Matrix Updated. Symbols: {len(self.matrix.columns)}")
                
        except Exception as e:
            # Silent fail is safer here than crashing execution logic
            print(f"[CORR WARN] Matrix update failed: {e}")

    def check_correlation(self, new_symbol, open_positions_list):
        """
        Gatekeeper Method. O(1) Check against cached matrix.
        Returns: (Bool safe_to_trade, String reason)
        """
        # Ensure Matrix is fresh
        self._update_matrix()
        
        # Bypass if matrix isn't ready (Don't block trading due to math error)
        if self.matrix is None: 
            return True, "Safe (No Matrix)"
        
        if new_symbol not in self.matrix.columns: 
            return True, "Safe (New Symbol)"

        # Check against every currently open position
        for pos in open_positions_list:
            existing_sym = pos.get('s')
            
            # Skip self-check (logic handled by exposure duplicate check)
            if existing_sym == new_symbol: 
                continue 
            
            if existing_sym in self.matrix.columns:
                try:
                    # O(1) Lookup
                    val = self.matrix.loc[new_symbol, existing_sym]
                    
                    # Check for Strong Positive OR Negative correlation?
                    # Original logic was abs(val) > threshold.
                    # This implies we block Hedging correlated pairs (EURUSD vs USDCHF) too.
                    # That is safer for generic systems. Retaining logic.
                    if abs(val) > self.threshold:
                        # Determine correlation type for reporting
                        c_type = "Pos" if val > 0 else "Neg"
                        return False, f"Corr {c_type} w/ {existing_sym} ({val:.2f})"
                except KeyError:
                    continue

        return True, "Safe"