import unittest
import json
from dataclasses import FrozenInstanceError
from src.arbiter.intent import Intent, grade_rank
from src.core.events import Event, IntentEmitted, IntentBlocked


class TestIntentModel(unittest.TestCase):
    def test_intent_frozen_immutability(self):
        """Intent must be frozen; attempting to mutate raises FrozenInstanceError."""
        i = Intent(
            strategy_id="sb_v15",
            symbol="EURUSD",
            direction="BUY",
            kind="MARKET",
            price=1.0950,
            sl=1.0900,
            tp=1.1050,
            grade="A+"
        )
        with self.assertRaises(FrozenInstanceError):
            i.price = 1.0900

    def test_effective_thesis_auto_vs_explicit(self):
        """effective_thesis() returns thesis_id if provided, else auto (symbol:direction:price:sl)."""
        # Auto case
        i1 = Intent(
            strategy_id="sb_v15",
            symbol="EURUSD",
            direction="BUY",
            kind="MARKET",
            price=1.0950,
            sl=1.0900,
            tp=1.1050
        )
        self.assertEqual(i1.effective_thesis(), "EURUSD:BUY:1.095:1.09")

        # Explicit case
        i2 = Intent(
            strategy_id="sb_v15",
            symbol="EURUSD",
            direction="BUY",
            kind="MARKET",
            price=1.0950,
            sl=1.0900,
            tp=1.1050,
            thesis_id="custom_thesis_123"
        )
        self.assertEqual(i2.effective_thesis(), "custom_thesis_123")

    def test_grade_rank_ordering(self):
        """grade_rank returns correct ordering: A++ > A+ > A > B+ > B > C > unknown=0."""
        self.assertEqual(grade_rank("A++"), 6)
        self.assertEqual(grade_rank("A+"), 5)
        self.assertEqual(grade_rank("A"), 4)
        self.assertEqual(grade_rank("B+"), 3)
        self.assertEqual(grade_rank("B"), 2)
        self.assertEqual(grade_rank("C"), 1)
        self.assertEqual(grade_rank("unknown"), 0)
        self.assertEqual(grade_rank(""), 0)

    def test_events_roundtrip_via_from_dict(self):
        """Both IntentEmitted and IntentBlocked must roundtrip via Event.from_dict."""
        # IntentEmitted
        e1 = IntentEmitted(
            strategy_id="sb_v15",
            symbol="EURUSD",
            direction="BUY",
            kind="MARKET",
            grade="A+",
            thesis="EURUSD:BUY:1.095:1.09"
        )
        d1 = e1.to_dict()
        e1_restored = Event.from_dict(d1)
        self.assertEqual(e1, e1_restored)
        self.assertIsInstance(e1_restored, IntentEmitted)

        # IntentBlocked
        e2 = IntentBlocked(
            strategy_id="sb_v15",
            symbol="EURUSD",
            direction="BUY",
            rule="grade_too_low",
            detail="C < A"
        )
        d2 = e2.to_dict()
        e2_restored = Event.from_dict(d2)
        self.assertEqual(e2, e2_restored)
        self.assertIsInstance(e2_restored, IntentBlocked)

    def test_to_payload_json_serializable(self):
        """Intent.to_payload() must produce JSON-serializable output."""
        i = Intent(
            strategy_id="sb_v15",
            symbol="EURUSD",
            direction="BUY",
            kind="MARKET",
            price=1.0950,
            sl=1.0900,
            tp=1.1050,
            grade="A+",
            confidence=0.95,
            thesis_id="custom_thesis",
            priority=10
        )
        payload = i.to_payload()
        # Should not raise
        json_str = json.dumps(payload)
        self.assertIsInstance(json_str, str)
        # Verify round-trip
        restored = json.loads(json_str)
        self.assertEqual(restored["strategy_id"], "sb_v15")
        self.assertEqual(restored["symbol"], "EURUSD")
        self.assertEqual(restored["price"], 1.0950)


if __name__ == "__main__":
    unittest.main()
