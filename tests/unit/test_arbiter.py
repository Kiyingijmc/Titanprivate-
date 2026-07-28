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


class TestRuleOrderInvariant(unittest.TestCase):
    def test_dedup_then_opposition_combined_same_symbol(self):
        """Rule 2 (dedup) MUST run before rule 3 (opposition), and dedup losers
        must never leak into the opposition comparison.

        One cycle, one symbol, three intents: BUY A+ (strat a), BUY B (strat b),
        SELL A (strat c), policy higher_grade_wins.

        Expected: dedup collapses the BUY group to the A+ (blocking the B BUY
        with rule='dedup'), THEN opposition pits BUY A+ vs SELL A and the A+
        wins (blocking the SELL with rule='opposition'). The blocked-event
        ORDER (dedup before opposition) fails if the rules were swapped, and
        the exact per-loser rule attribution fails if the B BUY leaked into
        the opposition stage."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"opposition_policy": "higher_grade_wins"}, publish=pub)

        buy_best = make_intent(strategy_id="strat_a", direction="BUY", grade="A+", thesis_id="t-a")
        buy_dup = make_intent(strategy_id="strat_b", direction="BUY", grade="B", thesis_id="t-b")
        sell = make_intent(strategy_id="strat_c", direction="SELL", grade="A", thesis_id="t-c")
        arb.submit(buy_best)
        arb.submit(buy_dup)
        arb.submit(sell)
        approved = arb.resolve(open_positions=[], bar_key="b1")

        self.assertEqual(len(approved), 1)
        self.assertIs(approved[0], buy_best)

        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 2)
        # Order is load-bearing: dedup (rule 2) must have fired before
        # opposition (rule 3).
        self.assertEqual(blocked[0].rule, "dedup")
        self.assertEqual(blocked[0].strategy_id, "strat_b")
        self.assertEqual(blocked[0].direction, "BUY")
        self.assertEqual(blocked[1].rule, "opposition")
        self.assertEqual(blocked[1].strategy_id, "strat_c")
        self.assertEqual(blocked[1].direction, "SELL")


class TestBarKeyAging(unittest.TestCase):
    def test_same_bar_key_does_not_double_age_thesis(self):
        """Thesis aging counts DISTINCT bar_key values, not resolve() calls.
        Multiple resolves on the same bar_key must not advance the age."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"thesis_ttl_bars": 2}, publish=pub)

        # Thesis T first seen at bar k1.
        t1 = make_intent(thesis_id="T")
        arb.submit(t1)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="k1"), [t1])

        # Two empty resolves on the SAME new bar_key k2: only ONE distinct
        # key has elapsed, however many times we resolve.
        arb.resolve(open_positions=[], bar_key="k2")
        arb.resolve(open_positions=[], bar_key="k2")

        # Replay T at k2 -> age is 1 distinct key (< ttl=2) -> still BLOCKED.
        t2 = make_intent(thesis_id="T")
        arb.submit(t2)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="k2"), [])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "thesis_dedup")

        # Replay T at k3 -> age is now 2 distinct keys (>= ttl=2) -> allowed.
        t3 = make_intent(thesis_id="T")
        arb.submit(t3)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="k3"), [t3])


class TestTimeframeScopedAging(unittest.TestCase):
    """v15 Advisory C: thesis aging is denominated in bars of the thesis's OWN
    timeframe. A single global bar counter conflates them — once any M5
    strategy runs, ~12 M5 closes per hour would age an H1 thesis out in one
    hour instead of `thesis_ttl_bars` hours."""

    def test_m5_bar_advances_do_not_age_an_h1_thesis(self):
        """THE DEFECT. An H1 thesis seen at H1 bar 1 must still be replay-blocked
        on H1 bar 2, no matter how many M5 bars closed in between."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"thesis_ttl_bars": 12}, publish=pub)

        # H1 thesis T first seen on H1 bar h1.
        t1 = make_intent(thesis_id="T")
        arb.submit(t1)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h1", timeframe="H1"), [t1])

        # An M5 strategy runs: 12 M5 closes elapse within that same hour.
        for i in range(12):
            arb.resolve(open_positions=[], bar_key=f"m5-{i}", timeframe="M5")

        # Next H1 bar: only ONE H1 bar has elapsed, so T is still a replay.
        t2 = make_intent(thesis_id="T")
        arb.submit(t2)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h2", timeframe="H1"), [])
        blocked = pub.of_type(IntentBlocked)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "thesis_dedup")

    def test_h1_advances_do_not_age_an_m5_thesis(self):
        """The symmetric case: an H1 counter tick must not age an M5 thesis."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"thesis_ttl_bars": 3}, publish=pub)

        m1 = make_intent(thesis_id="M")
        arb.submit(m1)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="m1", timeframe="M5"), [m1])

        # Three H1 bars elapse (>= ttl) but zero further M5 bars.
        for i in range(3):
            arb.resolve(open_positions=[], bar_key=f"h-{i}", timeframe="H1")

        # Next M5 bar: age is 1 M5 bar (< ttl=3) -> still blocked.
        m2 = make_intent(thesis_id="M")
        arb.submit(m2)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="m2", timeframe="M5"), [])
        self.assertEqual(pub.of_type(IntentBlocked)[0].rule, "thesis_dedup")

    def test_h1_only_aging_expires_at_exactly_ttl_advances(self):
        """No off-by-one drift from the per-timeframe refactor: with ttl=3 the
        thesis is blocked at ages 1 and 2 and allowed at exactly age 3."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"thesis_ttl_bars": 3}, publish=pub)

        seed = make_intent(thesis_id="T")
        arb.submit(seed)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h1", timeframe="H1"), [seed])

        for age, key in ((1, "h2"), (2, "h3")):
            replay = make_intent(thesis_id="T")
            arb.submit(replay)
            self.assertEqual(
                arb.resolve(open_positions=[], bar_key=key, timeframe="H1"), [],
                f"thesis must still be blocked at age {age} (< ttl=3)",
            )

        allowed = make_intent(thesis_id="T")
        arb.submit(allowed)
        self.assertEqual(
            arb.resolve(open_positions=[], bar_key="h4", timeframe="H1"), [allowed],
            "thesis must be allowed again at exactly age 3 (== ttl)",
        )

    def test_blocked_replay_does_not_refresh_its_stored_index(self):
        """A spam sequence must not keep resetting its own TTL clock: the
        blocked replay's sighting is NOT recorded, so the block still expires."""
        pub = RecordingPublisher()
        arb = Arbiter(config={"thesis_ttl_bars": 2}, publish=pub)

        seed = make_intent(thesis_id="T")
        arb.submit(seed)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h1", timeframe="H1"), [seed])

        # Spam the same thesis on the next bar -> blocked, index NOT refreshed.
        spam = make_intent(thesis_id="T")
        arb.submit(spam)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h2", timeframe="H1"), [])

        # If the block had refreshed the index, this would still be blocked.
        allowed = make_intent(thesis_id="T")
        arb.submit(allowed)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h3", timeframe="H1"), [allowed])

    def test_same_bar_key_does_not_double_age_within_a_timeframe(self):
        """The per-timeframe counter keeps the 'distinct bar_key' rule: repeated
        resolves on one timeframe's same bar_key never advance that counter."""
        arb = Arbiter(config={"thesis_ttl_bars": 2})

        t1 = make_intent(thesis_id="T")
        arb.submit(t1)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h1", timeframe="H1"), [t1])

        for _ in range(5):
            arb.resolve(open_positions=[], bar_key="h2", timeframe="H1")

        # Only one distinct H1 key elapsed -> age 1 (< ttl=2) -> blocked.
        t2 = make_intent(thesis_id="T")
        arb.submit(t2)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="h2", timeframe="H1"), [])

    def test_thesis_memory_is_bounded_per_timeframe(self):
        """Memory stays bounded: each timeframe's entries purge within its own
        trailing TTL window, independently of the other timeframe's traffic."""
        arb = Arbiter(config={"thesis_ttl_bars": 2})

        arb.submit(make_intent(thesis_id="H"))
        arb.resolve(open_positions=[], bar_key="h1", timeframe="H1")
        arb.submit(make_intent(thesis_id="M"))
        arb.resolve(open_positions=[], bar_key="m1", timeframe="M5")
        self.assertEqual(set(arb._thesis_memory), {"H", "M"})

        # Two M5 bars elapse: the M5 entry ages out, the H1 entry does NOT.
        arb.resolve(open_positions=[], bar_key="m2", timeframe="M5")
        arb.resolve(open_positions=[], bar_key="m3", timeframe="M5")
        self.assertEqual(set(arb._thesis_memory), {"H"})

        # Two H1 bars elapse: the H1 entry ages out too.
        arb.resolve(open_positions=[], bar_key="h2", timeframe="H1")
        arb.resolve(open_positions=[], bar_key="h3", timeframe="H1")
        self.assertEqual(set(arb._thesis_memory), set())

    def test_default_timeframe_keeps_every_caller_in_one_bucket(self):
        """Byte-compatibility: callers that omit `timeframe` (every pre-existing
        fixture, and the whole SB-H1-only live path before it passes one) all
        share a single counter — exactly the old behavior."""
        arb = Arbiter(config={"thesis_ttl_bars": 2})

        t1 = make_intent(thesis_id="T")
        arb.submit(t1)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="b1"), [t1])

        arb.resolve(open_positions=[], bar_key="b2")

        t2 = make_intent(thesis_id="T")
        arb.submit(t2)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="b2"), [])

        t3 = make_intent(thesis_id="T")
        arb.submit(t3)
        self.assertEqual(arb.resolve(open_positions=[], bar_key="b3"), [t3])


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
