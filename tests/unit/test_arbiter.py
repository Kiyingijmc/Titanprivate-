import unittest
from src.arbiter.intent import Intent
from src.arbiter.arbiter import Arbiter
from src.core.events import IntentEmitted, IntentBlocked


def make_intent(strategy_id="sb_v15", symbol="EURUSD", direction="BUY", kind="MARKET",
                 price=1.1000, sl=1.0950, tp=1.1100, grade="A", priority=50, thesis_id=""):
    return Intent(
        strategy_id=strategy_id, symbol=symbol, direction=direction, kind=kind,
        price=price, sl=sl, tp=tp, grade=grade, priority=priority, thesis_id=thesis_id,
    )


class RecordingPublisher:
    """Captures every published Event for assertion."""
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)

    def of_type(self, cls):
        return [e for e in self.events if isinstance(e, cls)]


class TestArbiterSingleIntent(unittest.TestCase):
    def test_single_intent_passes_untouched(self):
        """The SilverBullet transparency guarantee: a lone intent returns as the
        SAME object (identity, not just equality) — the arbiter must not rebuild
        or copy intents it approves."""
        pub = RecordingPublisher()
        arb = Arbiter(publish=pub)
        intent = make_intent()
        arb.submit(intent)
        approved = arb.resolve(open_positions=[], bar_key="b1")
        self.assertEqual(len(approved), 1)
        self.assertIs(approved[0], intent)
        # submit publishes IntentEmitted
        self.assertEqual(len(pub.of_type(IntentEmitted)), 1)
        # no blocks
        self.assertEqual(len(pub.of_type(IntentBlocked)), 0)


class TestThesisDedup(unittest.TestCase):
    def test_thesis_replay_within_ttl_blocked_then_allowed_after_ttl(self):
        """Same thesis resubmitted on the very next bar is blocked (thesis_dedup);
        once thesis_ttl_bars distinct bar_keys have elapsed, it is allowed again."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"thesis_ttl_bars": 2}, publish=pub)

        i1 = make_intent(thesis_id="thesis-X")
        arb.submit(i1)
        approved1 = arb.resolve(open_positions=[], bar_key="b1")
        self.assertEqual(approved1, [i1])

        # Replay on the very next distinct bar_key -> blocked
        i2 = make_intent(thesis_id="thesis-X")
        arb.submit(i2)
        approved2 = arb.resolve(open_positions=[], bar_key="b2")
        self.assertEqual(approved2, [])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "thesis_dedup")

        # After thesis_ttl_bars=2 distinct bar_keys have elapsed -> allowed
        i3 = make_intent(thesis_id="thesis-X")
        arb.submit(i3)
        approved3 = arb.resolve(open_positions=[], bar_key="b3")
        self.assertEqual(approved3, [i3])


class TestSameSymbolSameDirectionDedup(unittest.TestCase):
    def test_dedup_keeps_best_grade_and_blocks_loser(self):
        """Two intents, same symbol+direction, different grades: keep the A+,
        block the B and publish IntentBlocked(rule='dedup') for the loser."""
        pub = RecordingPublisher()
        arb = Arbiter(publish=pub)

        winner = make_intent(strategy_id="strat_a", grade="A+", thesis_id="t-a")
        loser = make_intent(strategy_id="strat_b", grade="B", thesis_id="t-b")
        arb.submit(loser)
        arb.submit(winner)
        approved = arb.resolve(open_positions=[], bar_key="b1")

        self.assertEqual(approved, [winner])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "dedup")
        self.assertEqual(blocked[0].strategy_id, "strat_b")


class TestOppositionPolicy(unittest.TestCase):
    def test_higher_grade_wins_picks_winner(self):
        pub = RecordingPublisher()
        arb = Arbiter(config={"opposition_policy": "higher_grade_wins"}, publish=pub)

        buy = make_intent(strategy_id="strat_buy", direction="BUY", grade="A+", thesis_id="t-buy")
        sell = make_intent(strategy_id="strat_sell", direction="SELL", grade="B", thesis_id="t-sell")
        arb.submit(sell)
        arb.submit(buy)
        approved = arb.resolve(open_positions=[], bar_key="b1")

        self.assertEqual(approved, [buy])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "opposition")
        self.assertEqual(blocked[0].strategy_id, "strat_sell")

    def test_higher_grade_wins_equal_grades_blocks_both(self):
        pub = RecordingPublisher()
        arb = Arbiter(config={"opposition_policy": "higher_grade_wins"}, publish=pub)

        buy = make_intent(strategy_id="strat_buy", direction="BUY", grade="A", thesis_id="t-buy")
        sell = make_intent(strategy_id="strat_sell", direction="SELL", grade="A", thesis_id="t-sell")
        arb.submit(buy)
        arb.submit(sell)
        approved = arb.resolve(open_positions=[], bar_key="b1")

        self.assertEqual(approved, [])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 2)
        self.assertTrue(all(b.rule == "opposition" for b in blocked))

    def test_block_both_policy_blocks_both_regardless_of_grade(self):
        pub = RecordingPublisher()
        arb = Arbiter(config={"opposition_policy": "block_both"}, publish=pub)

        buy = make_intent(strategy_id="strat_buy", direction="BUY", grade="A+", thesis_id="t-buy")
        sell = make_intent(strategy_id="strat_sell", direction="SELL", grade="C", thesis_id="t-sell")
        arb.submit(buy)
        arb.submit(sell)
        approved = arb.resolve(open_positions=[], bar_key="b1")

        self.assertEqual(approved, [])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 2)
        self.assertTrue(all(b.rule == "opposition" for b in blocked))


class TestSymbolCap(unittest.TestCase):
    def test_symbol_cap_blocks_when_open_position_exists(self):
        pub = RecordingPublisher()
        arb = Arbiter(config={"max_positions_per_symbol": 1}, publish=pub)

        intent = make_intent(symbol="EURUSD", direction="BUY")
        arb.submit(intent)
        open_positions = [{"t": 1, "s": "EURUSD", "p": 1.1, "dir": "BUY"}]
        approved = arb.resolve(open_positions=open_positions, bar_key="b1")

        self.assertEqual(approved, [])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "symbol_cap")

    def test_unknown_direction_open_position_counts_for_cap_not_opposition(self):
        """An open position with no 'dir' key still saturates the per-symbol cap,
        but it must never trigger the opposition rule (which only ever compares
        intents submitted THIS cycle against each other)."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"max_positions_per_symbol": 1}, publish=pub)

        intent = make_intent(symbol="EURUSD", direction="BUY")
        arb.submit(intent)
        open_positions = [{"t": 1, "s": "EURUSD", "p": 1.1}]  # no 'dir' key
        approved = arb.resolve(open_positions=open_positions, bar_key="b1")

        self.assertEqual(approved, [])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "symbol_cap")
        self.assertNotEqual(blocked[0].rule, "opposition")


class TestTotalCap(unittest.TestCase):
    def test_total_cap_enforced_across_symbols(self):
        """approved-this-cycle intents on DIFFERENT symbols still saturate the
        total cap even with no open positions."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"max_total_positions": 2, "max_positions_per_symbol": 1}, publish=pub)

        i1 = make_intent(symbol="EURUSD", grade="A++", thesis_id="t1")
        i2 = make_intent(symbol="GBPUSD", grade="A+", thesis_id="t2")
        i3 = make_intent(symbol="XAUUSD", grade="A", thesis_id="t3")
        arb.submit(i1)
        arb.submit(i2)
        arb.submit(i3)
        approved = arb.resolve(open_positions=[], bar_key="b1")

        self.assertEqual(approved, [i1, i2])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "total_cap")
        self.assertEqual(blocked[0].symbol, "XAUUSD")


class TestStats(unittest.TestCase):
    def test_stats_counters_accurate(self):
        pub = RecordingPublisher()
        arb = Arbiter(config={"max_total_positions": 2, "max_positions_per_symbol": 1}, publish=pub)

        i1 = make_intent(symbol="EURUSD", grade="A++", thesis_id="t1")
        i2 = make_intent(symbol="GBPUSD", grade="A+", thesis_id="t2")
        i3 = make_intent(symbol="XAUUSD", grade="A", thesis_id="t3")
        arb.submit(i1)
        arb.submit(i2)
        arb.submit(i3)
        arb.resolve(open_positions=[], bar_key="b1")

        stats = arb.stats()
        self.assertEqual(stats["submitted"], 3)
        self.assertEqual(stats["approved"], 2)
        self.assertEqual(stats["blocked_by"], {"total_cap": 1})


class TestPublishNone(unittest.TestCase):
    def test_publish_none_is_safe(self):
        """No publish callable configured -> submit/resolve must not raise, even
        on a path that would normally emit IntentBlocked."""
        arb = Arbiter(config={"opposition_policy": "block_both"}, publish=None)

        buy = make_intent(direction="BUY", thesis_id="t-buy")
        sell = make_intent(direction="SELL", thesis_id="t-sell")
        arb.submit(buy)
        arb.submit(sell)
        approved = arb.resolve(open_positions=[], bar_key="b1")

        self.assertEqual(approved, [])
        stats = arb.stats()
        self.assertEqual(stats["blocked_by"], {"opposition": 2})


if __name__ == "__main__":
    unittest.main()
