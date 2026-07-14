"""MA-slope baseline for the Gyroscope gate (novel-arsenal 14.7 step 2):
the naive competitor Gyroscope must beat on the identical exit model and
cost pipeline (gate criterion 6). MARKET entry when the sign of the
ma_window-bar SMA slope FLIPS; stop = stop_atr * ATR(14); tp = rr_target *
risk. Memoryless apart from the previous slope sign per symbol -- this is
deliberately the dumbest defensible trend timer.
"""
from src.strategies.base_strategy import BaseStrategy
from src.analysis.atr_simple import last_atr


class MaSlopeBaseline(BaseStrategy):
    def __init__(self, config, logger):
        super().__init__("MaSlopeBaseline", config, logger)
        self.timeframe = str(config.get('timeframe', 'H1'))
        self.ma_window = int(config.get('ma_window', 24))
        self.stop_atr = float(config.get('stop_atr', 1.0))
        self.rr_target = float(config.get('rr_target', 2.0))
        self._prev_sign = {}  # symbol -> -1 | 0 | +1

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        if not self.validate_data(df, min_length=self.ma_window + 2, check_smc=False):
            return None
        closes = df['close']
        ma_now = float(closes.iloc[-self.ma_window:].mean())
        ma_prev = float(closes.iloc[-self.ma_window - 1:-1].mean())
        slope = ma_now - ma_prev
        sign = 1 if slope > 0 else (-1 if slope < 0 else 0)
        prev = self._prev_sign.get(symbol, 0)
        self._prev_sign[symbol] = sign
        if sign == 0 or sign == prev:
            return None
        atr = last_atr(df)
        if atr <= 0:
            return None
        price = float(closes.iloc[-1])
        risk = self.stop_atr * atr
        if sign > 0:
            return {'signal': 'BUY', 'type': 'MARKET', 'price': price,
                    'sl': price - risk, 'tp': price + self.rr_target * risk}
        return {'signal': 'SELL', 'type': 'MARKET', 'price': price,
                'sl': price + risk, 'tp': price - self.rr_target * risk}
