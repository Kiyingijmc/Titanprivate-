# tests/unit/test_gambit_strategy.py
# Chassis behavior: windows, one-per-session, precedence, cost floor,
# spread guard. Detector internals are covered by test_gambit_setups.
import asyncio
import unittest
from datetime import datetime, timezone as dt_tz, timedelta
import pandas as pd
import pytz

from src.strategies.models.gambit import Gambit

NY = pytz.timezone("US/Eastern")

CONFIG = {
    "enabled": True,
    "timeframe": "M5",
    "rr": 2.0,
    "broker_gmt_offset": 0,       # tests use UTC epochs == broker time
    "sessions": {
        "london": {"window": ["02:00", "05:00"], "range": ["18:00", "02:00"]},
        "ny_am": {"window": ["08:30", "11:00"], "range": ["02:00", "08:30"]},
    },
    "symbol_sessions": {"US30": ["ny_am"], "XAUUSD": ["london", "ny_am"]},
    "setups": {
        "judas": {"enabled": True, "sweep_ttl_bars": 12,
                  "body_min_atr": 0.8, "stop_buffer_atr": 0.2},
        "reprise": {"enabled": True, "body_min_atr": 0.8,
                    "stop_buffer_atr": 0.2},
    },
    "cost_floor_mult": 4,
    "min_stop_price": {"US30": 10.0, "XAUUSD": 1.0},
    "max_spread_price": {"US30": 12.0, "XAUUSD": 0.9},
    "pairs": ["US30", "XAUUSD"],
}


class _Logger:
    def __init__(self):
        self.events = []

    def log_event(self, *a, **k):
        self.events.append(a)


def m5_frame(last_ny, n=150, price=100.0, atr=1.0):
    """Enriched-look M5 frame ending at NY wall-clock `last_ny`.
    'time' = epoch seconds (broker_gmt_offset=0 => UTC == broker)."""
    end = NY.localize(last_ny).astimezone(dt_tz.utc)
    times = [(end - timedelta(minutes=5 * (n - 1 - i))).timestamp()
             for i in range(n)]
    df = pd.DataFrame({
        "time": times,
        "open": [price] * n, "high": [price + 0.1] * n,
        "low": [price - 0.1] * n, "close": [price] * n,
        "ATR": [atr] * n,
        "is_swing_high": False, "is_swing_low": False,
        "is_fvg_bull": False, "is_fvg_bear": False,
        "fvg_top": 0.0, "fvg_bottom": 0.0,
    })
    return df


def arm_reprise_sell(df, entry=99.5, far_hi=112.0):
    i = len(df) - 1
    df.loc[i, "open"] = 100.5
    df.loc[i, "close"] = 99.0          # body 1.5 >= 0.8*ATR
    df.loc[df.index[i - 2], "high"] = far_hi
    df.loc[i, "is_fvg_bear"] = True
    df.loc[i, "fvg_bottom"] = entry
    df.loc[i, "fvg_top"] = 100.2
    return df


def ctx(symbol, ny_hhmmss, bias="BEARISH", spread=None):
    return {"symbol": symbol, "bias": bias, "liquidity": {},
            "ny_time": f"{ny_hhmmss} EDT", "smc_df": None, "spread": spread}


def run(strat, df, c):
    # asyncio.get_event_loop() deprecation-warns on this interpreter
    # (3.12, no running loop); match tests/unit/test_almanac_strategy.py's
    # asyncio.run() pattern instead (brief explicitly allows this swap).
    return asyncio.run(strat.on_new_candle(df, context=c))


class TestGambitChassis(unittest.TestCase):
    def setUp(self):
        self.log = _Logger()
        self.strat = Gambit(CONFIG, self.log)

    def test_outside_window_returns_none(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 7, 0)))
        self.assertIsNone(run(self.strat, df, ctx("US30", "07:00:00")))

    def test_reprise_fires_in_window(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        out = run(self.strat, df, ctx("US30", "09:00:00"))
        self.assertIsNotNone(out)
        self.assertEqual(out["setup"], "reprise")
        self.assertEqual(out["signal"], "SELL")

    def test_window_end_exclusive(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 11, 0)))
        self.assertIsNone(run(self.strat, df, ctx("US30", "11:00:00")))

    def test_symbol_not_scoped_to_session(self):
        # US30 is ny_am-only; 03:00 is the london window.
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 3, 0)))
        self.assertIsNone(run(self.strat, df, ctx("US30", "03:00:00")))

    def test_one_intent_per_session(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNotNone(run(self.strat, df, ctx("US30", "09:00:00")))
        df2 = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 30)))
        self.assertIsNone(run(self.strat, df2, ctx("US30", "09:30:00")))

    def test_cost_floor_blocks_thin_stop(self):
        # risk = |sl-entry| = |106+0.2 - 99.5|? No: STRUCT d includes far
        # extreme. Use a NEAR far-extreme so d < min_stop_price (10.0).
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)),
                              far_hi=100.6)     # d = 1.1 + 0.2 = 1.3 < 10
        self.assertIsNone(run(self.strat, df, ctx("US30", "09:00:00")))

    def test_missing_min_stop_symbol_fails_safe(self):
        cfg = dict(CONFIG, min_stop_price={}, pairs=["US30"])
        strat = Gambit(cfg, self.log)
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNone(run(strat, df, ctx("US30", "09:00:00")))

    def test_spread_guard(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNone(
            run(self.strat, df, ctx("US30", "09:00:00", spread=13.0)))
        # at/below the cap trades normally
        df2 = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNotNone(
            run(self.strat, df2, ctx("US30", "09:00:00", spread=11.0)))

    def test_disabled_setup_never_fires(self):
        cfg = dict(CONFIG)
        cfg["setups"] = {"judas": dict(CONFIG["setups"]["judas"]),
                         "reprise": {"enabled": False, "body_min_atr": 0.8,
                                     "stop_buffer_atr": 0.2}}
        strat = Gambit(cfg, self.log)
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNone(run(strat, df, ctx("US30", "09:00:00")))

    def test_timeframe_and_pairs(self):
        self.assertEqual(self.strat.timeframe, "M5")
        self.assertEqual(self.strat.pairs, ["US30", "XAUUSD"])


class TestGambitRegistry(unittest.TestCase):
    def test_manifest_loads_and_stays_research(self):
        from pathlib import Path
        from src.strategies.manifest import load_manifests
        from src.strategies.registry import StrategyRegistry
        root = Path(__file__).resolve().parents[2]
        manifests = load_manifests(root / "config" / "manifests")
        ids = {m.id for m in manifests}
        self.assertIn("gambit", ids)
        gm = next(m for m in manifests if m.id == "gambit")
        self.assertEqual(gm.status, "research")
        self.assertEqual(gm.timeframe, "M5")
        # Registry with ONLY the gambit manifest: other strategies' config
        # blocks aren't this test's concern.
        reg = StrategyRegistry([gm], {"gambit": dict(CONFIG)}, _Logger())
        reg.load_all()
        reg.activate_eligible()
        names = [s.name for s in reg.active_instances()]
        self.assertNotIn("Gambit", names)


if __name__ == "__main__":
    unittest.main()
