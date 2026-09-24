"""Invalid inputs must not escape SilverBullet as executable decisions."""
import unittest

import pandas as pd

from src.strategies.models.silver_bullet import SilverBullet
from tests.unit.test_strategy_timeframe import MockLogger, sb_frame


class SilverBulletInputs(unittest.IsolatedAsyncioTestCase):
    async def decision(self, frame, config=None, context=None):
        strategy = SilverBullet({'windows': [[0, 24]], **(config or {})}, MockLogger())
        return await strategy.on_new_candle(
            frame, context={'ny_time': '10:00:00'} if context is None else context)

    async def test_nonfinite_and_nonpositive_prices_and_atr_are_rejected(self):
        for direction, edge in [('BUY', 'fvg_top'), ('SELL', 'fvg_bottom')]:
            for column in ('open', 'high', 'low', 'close', 'ATR', edge):
                for value in (float('nan'), float('inf'), -float('inf'), 0., -1.):
                    with self.subTest(direction=direction, column=column, value=value):
                        frame = sb_frame(direction)
                        frame.loc[frame.index[-1], column] = value
                        self.assertIsNone(await self.decision(frame))

    async def test_missing_required_price_columns_are_rejected(self):
        for column in ('open', 'high', 'low', 'close', 'fvg_bottom'):
            with self.subTest(column=column):
                self.assertIsNone(await self.decision(sb_frame().drop(columns=column)))

    async def test_impossible_candle_extremes_are_rejected(self):
        for column, value in [('high', 1.), ('low', 2.)]:
            frame = sb_frame()
            frame.loc[frame.index[-1], column] = value
            self.assertIsNone(await self.decision(frame))

    async def test_ambiguous_or_missing_direction_is_rejected(self):
        for bull, bear in [(True, True), (False, False), (pd.NA, True),
                           (float('nan'), True), ('False', True), (False, 2)]:
            with self.subTest(bull=bull, bear=bear):
                frame = sb_frame().astype({'is_fvg_bull': object, 'is_fvg_bear': object})
                frame.loc[frame.index[-1], ['is_fvg_bull', 'is_fvg_bear']] = [bull, bear]
                self.assertIsNone(await self.decision(frame))

    async def test_unused_fvg_edge_is_not_required(self):
        for direction, unused in [('BUY', 'fvg_bottom'), ('SELL', 'fvg_top')]:
            self.assertIsNotNone(await self.decision(sb_frame(direction).drop(columns=unused)))

    async def test_overflow_collapsed_risk_and_negative_exit_are_rejected(self):
        for direction in ('BUY', 'SELL'):
            for cfg in ({'risk_reward': 1e308, 'stop_atr': 1e308},
                        {'stop_atr': 1e-300}, {'stop_atr': 2000.}):
                with self.subTest(direction=direction, config=cfg):
                    self.assertIsNone(await self.decision(sb_frame(direction), cfg))

    async def test_malformed_clock_is_rejected(self):
        for clock in (None, 10, '', 'invalid', '24:00:00', '-1:00:00'):
            self.assertIsNone(await self.decision(sb_frame(), context={'ny_time': clock}))

    def test_invalid_risk_configuration_fails_at_construction(self):
        for key in ('risk_reward', 'stop_atr'):
            for value in (float('nan'), float('inf'), 0, -1):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        SilverBullet({key: value}, MockLogger())


if __name__ == '__main__':
    unittest.main()
