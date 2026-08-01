import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.policy import NewsPolicy

RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)

CONFIG = {"news": {"symbol_currencies": {
    "EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"], "XAUUSD": ["USD"],
}}}


def _event(currency="USD", importance="HIGH", title="Core PCE", when=RELEASE):
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title)


class CurrencyMapping(unittest.TestCase):
    def test_configured_symbol_uses_its_mapping(self):
        self.assertEqual(NewsPolicy(CONFIG).currencies_for("GBPJPY"), ["GBP", "JPY"])

    def test_unmapped_forex_pair_is_inferred_from_its_name(self):
        self.assertEqual(NewsPolicy({}).currencies_for("USDCHF"), ["USD", "CHF"])

    def test_unmapped_metal_infers_only_the_quote_currency(self):
        """XAU is not a fiat currency; XAUUSD is exposed to USD news."""
        self.assertEqual(NewsPolicy({}).currencies_for("XAUUSD"), ["USD"])

    def test_uninferrable_symbol_defaults_to_usd_not_empty(self):
        """An empty list would fail OPEN -- nothing would ever block."""
        self.assertEqual(NewsPolicy({}).currencies_for("US30"), ["USD"])

    def test_mapped_symbols_lists_configured_symbols(self):
        self.assertEqual(sorted(NewsPolicy(CONFIG).mapped_symbols()),
                         ["EURUSD", "GBPJPY", "XAUUSD"])


class OnlyRedFolderBlocks(unittest.TestCase):
    def test_high_impact_blocks(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNotNone(policy.blocking_event([_event()], "EURUSD", RELEASE))

    def test_medium_impact_never_blocks(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNone(
            policy.blocking_event([_event(importance="MEDIUM")], "EURUSD", RELEASE))

    def test_low_impact_never_blocks(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNone(
            policy.blocking_event([_event(importance="LOW")], "EURUSD", RELEASE))


class CurrencyMatching(unittest.TestCase):
    def test_usd_event_does_not_block_gbpjpy(self):
        """The proof-of-fix: GBPJPY holds no USD, so US CPI is irrelevant to it."""
        policy = NewsPolicy(CONFIG)
        self.assertIsNone(policy.blocking_event([_event("USD")], "GBPJPY", RELEASE))

    def test_gbp_event_blocks_gbpjpy(self):
        policy = NewsPolicy(CONFIG)
        event = _event("GBP", title="BOE Rate Decision")
        self.assertIsNotNone(policy.blocking_event([event], "GBPJPY", RELEASE))

    def test_jpy_event_blocks_gbpjpy(self):
        policy = NewsPolicy(CONFIG)
        event = _event("JPY", title="BOJ Policy Rate")
        self.assertIsNotNone(policy.blocking_event([event], "GBPJPY", RELEASE))

    def test_usd_event_blocks_xauusd(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNotNone(policy.blocking_event([_event("USD")], "XAUUSD", RELEASE))


class BlackoutWindow(unittest.TestCase):
    def _blocked_at(self, offset_min):
        policy = NewsPolicy(CONFIG)
        moment = RELEASE + timedelta(minutes=offset_min)
        return policy.blocking_event([_event()], "EURUSD", moment) is not None

    def test_blocked_thirty_minutes_before(self):
        self.assertTrue(self._blocked_at(-30))

    def test_blocked_at_the_release(self):
        self.assertTrue(self._blocked_at(0))

    def test_blocked_twenty_minutes_after(self):
        self.assertTrue(self._blocked_at(20))

    def test_clear_ninety_minutes_before(self):
        self.assertFalse(self._blocked_at(-90))

    def test_clear_forty_minutes_after(self):
        self.assertFalse(self._blocked_at(40))

    def test_reason_names_the_event(self):
        policy = NewsPolicy(CONFIG)
        event = policy.blocking_event([_event()], "EURUSD", RELEASE)
        self.assertIn("Core PCE", policy.reason_for(event, RELEASE))

    def test_blocked_exactly_at_the_window_open(self):
        """Exactly 60m before the release is INSIDE the blackout (inclusive edge)."""
        self.assertTrue(self._blocked_at(-60))

    def test_clear_one_minute_before_the_window_opens(self):
        self.assertFalse(self._blocked_at(-61))

    def test_blocked_exactly_at_the_window_close(self):
        """Exactly 30m after the release is still INSIDE the blackout (inclusive edge)."""
        self.assertTrue(self._blocked_at(30))

    def test_clear_one_minute_after_the_window_closes(self):
        self.assertFalse(self._blocked_at(31))


class Staleness(unittest.TestCase):
    def test_never_refreshed_counts_as_stale(self):
        self.assertTrue(NewsPolicy({}).is_stale(None))

    def test_fresh_cache_is_not_stale(self):
        self.assertFalse(NewsPolicy({}).is_stale(timedelta(hours=6)))

    def test_cache_past_the_ceiling_is_stale(self):
        self.assertTrue(NewsPolicy({}).is_stale(timedelta(hours=49)))

    def test_ceiling_is_configurable(self):
        policy = NewsPolicy({"news": {"max_cache_age_hours": 12}})
        self.assertTrue(policy.is_stale(timedelta(hours=13)))


if __name__ == "__main__":
    unittest.main()
