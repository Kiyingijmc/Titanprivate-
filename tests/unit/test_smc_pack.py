import unittest
import numpy as np
import pandas as pd
import pandas.testing as pdt

from src.features.feature_bus import FeatureBus
from src.features.packs.smc_pack import register_smc_pack
from src.analysis.smc_analyzer import SMCAnalyzer
from src.analysis.bias_engine import BiasEngine


def _make_frame(n=120):
    """Deterministic synthetic OHLC walk: numpy.random.default_rng(7)."""
    rng = np.random.default_rng(7)
    steps = rng.normal(0, 1, n).cumsum()
    close = 100 + steps
    open_ = close - rng.normal(0, 0.1, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.2, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.2, n))
    time = pd.date_range("2024-01-01", periods=n, freq="5min")
    return pd.DataFrame({
        "time": time, "open": open_, "high": high, "low": low, "close": close,
    })


def _bus():
    bus = FeatureBus()
    register_smc_pack(bus)
    bus.validate()
    return bus


class TestSmcPack(unittest.TestCase):
    def test_enriched_df_matches_direct_smc_analyzer(self):
        df = _make_frame()
        bus = _bus()
        token = df["time"].iloc[-1]

        via_bus = bus.evaluate("smc.enriched_df", "EURUSD", "M5", token=token, window=df)
        direct = SMCAnalyzer(df).process()

        pdt.assert_frame_equal(via_bus, direct)

    def test_bias_context_matches_direct_bias_engine(self):
        df = _make_frame()
        bus = _bus()
        token = df["time"].iloc[-1]

        via_bus = bus.evaluate("smc.bias_context", "EURUSD", "H1", token=token, h1_df=df)
        direct = BiasEngine(df).get_bias_context()

        self.assertEqual(via_bus[0], direct[0])
        self.assertEqual(via_bus[1], direct[1])

    def test_bias_context_cache_hit_pin_12x(self):
        df = _make_frame()
        bus = _bus()
        token = df["time"].iloc[-1]

        for _ in range(12):
            bus.evaluate("smc.bias_context", "EURUSD", "H1", token=token, h1_df=df)

        st = bus.stats()["smc.bias_context"]
        self.assertEqual((st["misses"], st["hits"]), (1, 11))

        new_df = _make_frame(n=121)
        new_token = new_df["time"].iloc[-1]
        bus.evaluate("smc.bias_context", "EURUSD", "H1", token=new_token, h1_df=new_df)

        st = bus.stats()["smc.bias_context"]
        self.assertEqual(st["misses"], 2)


if __name__ == "__main__":
    unittest.main()
