import unittest
from src.features.feature_bus import FeatureBus, ResourceSpec

def counter_spec(name, deps=(), calls=None, value=1):
    def compute(ctx):
        calls.append(name)
        return value + sum(ctx.deps.get(d, 0) for d in deps)
    return ResourceSpec(name=name, deps=tuple(deps), compute=compute)

class TestFeatureBus(unittest.TestCase):
    def test_memo_hit_on_same_token_recompute_on_new(self):
        calls, bus = [], FeatureBus()
        bus.register(counter_spec("a", calls=calls)); bus.validate()
        v1 = bus.evaluate("a", "EURUSD", "H1", token="t1")
        v2 = bus.evaluate("a", "EURUSD", "H1", token="t1")
        self.assertEqual((v1, v2, calls), (1, 1, ["a"]))          # hit
        bus.evaluate("a", "EURUSD", "H1", token="t2")
        self.assertEqual(calls, ["a", "a"])                        # token change -> miss
        st = bus.stats()["a"]
        self.assertEqual((st["hits"], st["misses"]), (1, 2))

    def test_dep_chain_topological_and_shared(self):
        calls, bus = [], FeatureBus()
        bus.register(counter_spec("base", calls=calls, value=10))
        bus.register(counter_spec("mid", deps=("base",), calls=calls, value=1))
        bus.register(counter_spec("top", deps=("mid", "base"), calls=calls, value=0))
        bus.validate()
        v = bus.evaluate("top", "X", "M5", token="t")
        self.assertEqual(v, 0 + (1 + 10) + 10)                     # top = mid + base
        self.assertEqual(calls, ["base", "mid", "top"])            # each computed ONCE, in order

    def test_scope_symbol_vs_symbol_tf(self):
        calls, bus = [], FeatureBus()
        s = counter_spec("sym", calls=calls); s = ResourceSpec(name="sym", compute=s.compute, scope="symbol")
        bus.register(s); bus.validate()
        bus.evaluate("sym", "X", "M5", token="t")
        bus.evaluate("sym", "X", "H1", token="t")                  # same symbol, diff tf -> HIT (scope=symbol)
        self.assertEqual(len(calls), 1)

    def test_cycle_and_unknown_dep_rejected(self):
        bus = FeatureBus()
        bus.register(ResourceSpec(name="a", deps=("b",), compute=lambda c: 1))
        bus.register(ResourceSpec(name="b", deps=("a",), compute=lambda c: 1))
        with self.assertRaises(ValueError):
            bus.validate()
        bus2 = FeatureBus()
        bus2.register(ResourceSpec(name="a", deps=("nope",), compute=lambda c: 1))
        with self.assertRaises(ValueError):
            bus2.validate()

    def test_duplicate_name_and_unknown_evaluate(self):
        bus = FeatureBus()
        bus.register(ResourceSpec(name="a", compute=lambda c: 1))
        with self.assertRaises(ValueError):
            bus.register(ResourceSpec(name="a", compute=lambda c: 2))
        with self.assertRaises(KeyError):
            bus.evaluate("missing", "X", "M5", token="t")

    def test_version_bump_cold_starts(self):
        calls, bus = [], FeatureBus()
        bus.register(counter_spec("a", calls=calls)); bus.validate()
        bus.evaluate("a", "X", "M5", token="t")
        bus._registry["a"] = ResourceSpec(name="a", compute=bus._registry["a"].compute, version="2")
        bus.evaluate("a", "X", "M5", token="t")
        self.assertEqual(len(calls), 2)

if __name__ == "__main__":
    unittest.main()
