# ==============================================================================
# FILE: src/utils/instrument.py
# TYPE: LOGIC REFINEMENT (Math & Standardization)
# AUDIT: 
#   1. Added Suffix Cleaning (Supports 'EURUSD.pro', 'BTCUSD_min').
#   2. Expanded Asset Class definitions (Indices, Crypto).
#   3. Standardized Pip Size logic for accurate Trailing Stops.
# STATUS: PRODUCTION READY
# ==============================================================================

import math
import re

class InstrumentHelper:
    """
    Mathematical helper for Instrument specifications.
    
    AUDIT UPGRADE:
    - Robust Symbol Normalization (Suffix Removal).
    - Expanded dictionary for Indices/Crypto asset detection.
    """
    
    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        """
        Removes broker-specific suffixes (e.g., "EURUSD.m" -> "EURUSD")
        to ensure asset class detection logic works universally.
        """
        if not symbol: return ""
        # Remove typical separators: dot, underscore, plus
        # Regex: Match first sequence of alphanumeric chars
        clean = re.split(r'[._+]', symbol)[0]
        return clean.upper()

    @staticmethod
    def get_decimals(symbol: str, price: float = 0.0) -> int:
        """Determines required decimal precision based on asset class."""
        s = InstrumentHelper._clean_symbol(symbol)
        
        # JPY Pairs (Forex)
        if "JPY" in s: 
            return 3
            
        # Crypto (BTC, ETH) - High price often implies 2 decimals, low price (XRP) 4+
        if any(c in s for c in ["BTC", "ETH", "LTC", "BNB"]):
            return 2
            
        # Indices (US30, NAS100, DAX)
        if any(c in s for c in ["US30", "NAS100", "SPX", "GER30", "DE40", "JP225"]):
            return 2 # Most brokers use 2 decimals for Indices now
            
        # Gold/Silver/Oil
        if any(c in s for c in ["XAU", "XAG", "WTI", "BRENT", "OIL"]):
            return 2
            
        # Standard Forex (EURUSD, GBPUSD)
        # Fallback to checking price magnitude if standard logic is unsure
        if price > 0:
            if price > 20000: return 1 # Bitcoin-like
            if price > 500: return 2   # Index/Gold
            if price < 50: return 5    # Forex
            
        return 5

    @staticmethod
    def get_pip_size(symbol: str) -> float:
        """
        Returns the standardization unit for Risk Calc and Ratchet Stops.
        Used when Broker TickSize is unavailable.
        """
        s = InstrumentHelper._clean_symbol(symbol)
        
        # 1. Commodities (Gold/Silver/Oil) -> 0.10 (10 cents)
        if any(x in s for x in ["XAU", "XAG", "WTI", "BRENT", "OIL"]):
            return 0.10 
            
        # 2. JPY Pairs -> 0.01 (1 sen)
        if "JPY" in s:
            return 0.01
            
        # 3. Indices -> 1.0 (1 point)
        # Extended list for global indices support
        indices = ["US30", "NAS100", "NDX", "SPX", "DOW", "DE40", "GER30", "FRA40", "UK100"]
        if any(x in s for x in indices):
            return 1.0
            
        # 4. Crypto -> 1.0 (1 dollar moves)
        # Note: Volatile assumption, but better than 0.0001
        if any(x in s for x in ["BTC", "ETH"]):
            return 1.0
            
        # 5. Standard Forex -> 0.0001 (1 pip)
        return 0.0001

    @staticmethod
    def normalize_price(price: float, pip_size: float) -> float:
        """
        Strict rounding based on pip unit.
        Retains logic logic from v14 source, adding safety checks.
        """
        if price is None or price == 0: 
            return 0.0
        
        # Calculate decimals from pip_size logic
        # 0.0001 (Forex) -> 5 decimals (Pipette)
        # 0.01 (JPY) -> 3 decimals
        # 1.0 (Index) -> 2 decimals
        
        if pip_size <= 0.0001:
            return round(price, 5) 
        elif pip_size <= 0.01:
            return round(price, 3) 
        elif pip_size <= 0.1:
            return round(price, 2) 
        else:
            return round(price, 2)