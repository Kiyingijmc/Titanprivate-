# ==============================================================================
# FILE: src/strategies/base_strategy.py
# TYPE: INTERFACE UPDATE (Standardization)
# AUDIT: 
#   1. Added centralized Input Validation (DataFrame length & Column checks).
#   2. Implemented Runtime Activation Guard.
#   3. Standardized Logging signature.
# STATUS: PRODUCTION READY
# ==============================================================================

from abc import ABC, abstractmethod
import pandas as pd

class BaseStrategy(ABC):
    """
    The Parent Class for all Titan Strategies.
    
    AUDIT UPGRADE:
    - Provides Validation Helpers to prevent 'KeyError' crashes in child classes.
    - Manages Activation State (Active/Paused).
    """
    def __init__(self, name, config, logger):
        self.name = name
        self.config = config
        self.logger = logger
        # Default enabled unless config says otherwise
        self.active = self.config.get('enabled', True)
        # Timeframe whose candle close triggers this strategy (M5/M15/H1).
        # The controller routes closed candles to matching strategies only.
        self.timeframe = str(self.config.get('timeframe', 'M5'))
        # Required columns for most SMC strategies
        self._smc_columns = ['is_swing_high', 'is_swing_low', 'is_fvg_bull', 'is_fvg_bear', 'ATR']

    @abstractmethod
    async def analyze_tick(self, tick_data, history_df):
        """High-frequency tick processing (Optional logic)."""
        pass
        
    @abstractmethod
    async def on_new_candle(self, closed_candle, context=None):
        """
        Called when a candle closes.
        :param closed_candle: The Pandas DataFrame of the closed candle(s).
        :param context: Dictionary containing HTF Bias, Liquidity Levels, Time, etc.
        :return: Decision Dict or None
        """
        pass
    
    def validate_data(self, df, min_length=50, check_smc=True):
        """
        Helper: Validates that the DataFrame is ready for strategy processing.
        Prevents IndexErrors and KeyErrors in the logic.
        """
        if not self.active:
            return False
            
        if df is None or df.empty:
            return False
            
        if len(df) < min_length:
            return False
            
        if check_smc:
            # Vectorized check if all required columns are present
            if not all(col in df.columns for col in self._smc_columns):
                # We can log once per missing batch, or fail silently to avoid spam
                return False
                
        return True
        
    def log(self, message):
        """Standardized Logging Proxy."""
        if self.logger:
            self.logger.log_event("STRATEGY", self.name, message)