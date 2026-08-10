# ==============================================================================
# FILE: src/analysis/bias_engine.py
# TYPE: LOGIC ORCHESTRATION (SMC Context)
# AUDIT: 
#   1. Connects Vectorized MarketStructure to the Strategy Controller.
#   2. Enforces strict Higher Timeframe (HTF) context generation.
#   3. Adds Defensive checks for DataFrame sufficiency.
# STATUS: PRODUCTION READY
# ==============================================================================

import logging

from src.analysis.market_structure import MarketStructure
from src.analysis.liquidity import LiquidityEngine

# Under "TitanBot", not a bare __name__: AuditLogger._setup_logging is the
# project's ONLY logging configuration and it attaches its RotatingFileHandler
# to the logger named "TitanBot" (src/core/audit_logger.py:78). There is no
# basicConfig and no root handler, so a logger in a sibling hierarchy is
# handled by logging.lastResort -- bare stderr -- and never reaches
# data/logs/titan_system.log, which is where the operator actually looks
# (RS024 MINOR-1).
_LOG = logging.getLogger("TitanBot." + __name__)

class BiasEngine:
    """
    Titan Institutional Bias Determinator.
    
    Responsibility:
    - Analyze Higher Timeframe (H1/H4) to determine structural flow.
    - Identify Premium/Discount arrays via LiquidityEngine.
    """
    def __init__(self, df):
        """
        df: A DataFrame of Higher Timeframe candles (H1 or H4)
        """
        # Data integrity check happens in methods to allow lazy loading
        self.df = df

    def get_bias_context(self):
        """
        Analyzes Higher Timeframe Context.
        
        Returns: 
            bias (str): "BULLISH", "BEARISH", or "NEUTRAL"
            liquidity (dict): Locations of PDH, PDL, EQ, and Range Status.
        """
        # Safety Check: Need enough history for 5-bar fractals + rolling ATR
        if self.df is None or len(self.df) < 50:
            return "NEUTRAL", {}

        try:
            # 1. Structural Bias (Fractal Trend)
            ms = MarketStructure(self.df)
            
            # We use a wider fractal (5 bars) for H1 stability to avoid noise
            # Note: This calls the optimized Vectorized implementation now.
            df_analyzed = ms.identify_swings(left_bars=5, right_bars=5)
            
            # 1=Bull, -1=Bear, 0=Range
            numeric_bias = ms.get_market_bias() 
            
            bias_str = "NEUTRAL"
            if numeric_bias == 1: bias_str = "BULLISH"
            elif numeric_bias == -1: bias_str = "BEARISH"
            
            # 2. Liquidity & Range Analysis (PD Arrays)
            liq_engine = LiquidityEngine(self.df)
            
            # Returns dict: {'PDH': x, 'PDL': y, 'EQ': z, 'STATUS': 'DISCOUNT'}
            liquidity_levels = liq_engine.get_pd_arrays() 
            
            # 3. Context Synthesis
            # Returns raw data to Strategy Class for final filtering.
            return bias_str, liquidity_levels

        except Exception as e:
            # Fallback for safety - do not crash the bot on Context Error.
            # The fallback is NOT neutral in effect: "NEUTRAL" disables the
            # HTF filter, so the controller then lets BOTH directions
            # through. A persistent H1 data fault therefore degrades the
            # bias filter silently, and the only trace used to be a
            # commented-out print (audit 2026-08-07 D7). Log it: the
            # behaviour is unchanged, the fault is now visible.
            _LOG.warning(
                "BiasEngine.get_bias_context failed (%s: %s) - degrading to "
                "NEUTRAL; the HTF bias filter is not filtering.",
                type(e).__name__, e)
            return "NEUTRAL", {}