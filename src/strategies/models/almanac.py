"""Almanac: turn-of-month index overlay -- the arsenal's integration canary.

Zero fitted parameters by design (docs/strategies/almanac.md): long US30/US100
from the last trading day of the month through the third trading day of the
next. Entries are known months in advance, so any live-vs-backtest divergence
is an infrastructure bug, not a strategy question -- that is the point.

H1-routed with an internal calendar gate (the platform has no D1 routing;
data_store builds M5+H1 only). Consumes raw OHLC (`check_smc=False`); computes
its own daily ATR by resampling the H1 window on completed days. The exit is
time-based and lives in TradeManager's `time_exits` hook (same calendar,
`src/analysis/trading_days.py`) -- the TP here is a far anchor
(tp_risk_mult x risk, default 10) that keeps the ratchet dormant in practice
(L1 would need +3.82R inside a 3-day hold) while honouring the no-tp=0
registration convention.

Calendar is weekday-based; exchange holidays are deliberately ignored
(documented approximation -- one deterministic rule on both sides).
"""
import pandas as pd

from src.strategies.base_strategy import BaseStrategy
from src.analysis import trading_days


class Almanac(BaseStrategy):
    def __init__(self, config, logger):
        super().__init__("Almanac", config, logger)
        self.timeframe = str(config.get('timeframe', 'H1'))
        # Broker-time hour: enter on the first H1 close at/after this hour of
        # the month's last trading day.
        self.entry_hour = int(config.get('entry_hour', 16))
        self.stop_atr_d1 = float(config.get('stop_atr_d1', 2.0))
        # 14 (not the audit sketch's 20): the live H1 buffer holds 500 bars
        # (candle_maker.history_limit), ~21 trading days on a 23h index -- too
        # tight for ATR(20,D1) after dropping the partial current day.
        self.atr_period_d1 = int(config.get('atr_period_d1', 14))
        self.tp_risk_mult = float(config.get('tp_risk_mult', 10.0))
        self._entered = {}  # symbol -> "YYYY-MM" already traded this window

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        min_bars = (self.atr_period_d1 + 2) * 24
        if not self.validate_data(df, min_length=min_bars, check_smc=False):
            return None
        if 'time' not in df.columns:
            return None

        try:
            bar_time = pd.to_datetime(df['time'].iloc[-1])
        except (ValueError, TypeError):
            return None
        bar_date = bar_time.date()

        if not trading_days.is_last_trading_day(bar_date):
            return None
        if bar_time.hour < self.entry_hour:
            return None

        month_key = f"{bar_date.year:04d}-{bar_date.month:02d}"
        if self._entered.get(symbol) == month_key:
            return None

        atr_d1 = self._daily_atr(df)
        if atr_d1 is None or atr_d1 <= 0:
            return None

        price = float(df['close'].iloc[-1])
        risk = self.stop_atr_d1 * atr_d1
        # Mark before returning so a re-fed window cannot double-enter even if
        # the order send fails downstream (canary: predictability over retry).
        self._entered[symbol] = month_key

        self.log(f"📅 ALMANAC turn-of-month entry {symbol} @ {price}")
        return {'signal': 'BUY', 'type': 'MARKET', 'price': price,
                'sl': price - risk, 'tp': price + self.tp_risk_mult * risk}

    def _daily_atr(self, df):
        """ATR over completed daily bars resampled from the H1 window."""
        try:
            x = df[['time', 'high', 'low', 'close']].copy()
            x['time'] = pd.to_datetime(x['time'])
            daily = (x.set_index('time')
                      .resample('1D')
                      .agg({'high': 'max', 'low': 'min', 'close': 'last'})
                      .dropna())
            daily = daily.iloc[:-1]  # drop the partial current day
            if len(daily) < self.atr_period_d1 + 1:
                return None
            prev_close = daily['close'].shift(1)
            tr = pd.concat([
                daily['high'] - daily['low'],
                (daily['high'] - prev_close).abs(),
                (daily['low'] - prev_close).abs(),
            ], axis=1).max(axis=1)
            return float(tr.iloc[-self.atr_period_d1:].mean())
        except (KeyError, ValueError, TypeError):
            return None
