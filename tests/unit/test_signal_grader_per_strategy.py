"""Per-strategy grade floor (minimal P8 carve-out for non-SMC canaries).

signal_grading.per_strategy_min_grade maps a strategy NAME to its own floor,
overriding the global min_grade for that strategy only. Absent config keeps
today's behaviour exactly. Grades are still computed and journaled for every
signal -- only the pass/fail floor is per-strategy.
"""
import unittest

from src.analysis.signal_grader import SignalGrader


def grader(**grading):
    return SignalGrader({"signal_grading": grading})


class TestPerStrategyFloor(unittest.TestCase):
    def test_default_behaviour_unchanged(self):
        g = grader(enabled=True, min_grade="B")
        self.assertTrue(g.passes("B"))
        self.assertFalse(g.passes("C"))

    def test_strategy_override_lowers_floor(self):
        g = grader(enabled=True, min_grade="B",
                   per_strategy_min_grade={"Almanac": "C"})
        self.assertTrue(g.passes("C", "Almanac"))
        self.assertFalse(g.passes("C", "SilverBullet"))
        self.assertFalse(g.passes("C"))  # no strategy given -> global floor

    def test_strategy_override_can_raise_floor(self):
        g = grader(enabled=True, min_grade="B",
                   per_strategy_min_grade={"Gyroscope": "A"})
        self.assertFalse(g.passes("B", "Gyroscope"))
        self.assertTrue(g.passes("B", "SilverBullet"))

    def test_invalid_override_grade_ignored(self):
        g = grader(enabled=True, min_grade="B",
                   per_strategy_min_grade={"Almanac": "Z"})
        self.assertFalse(g.passes("C", "Almanac"))  # falls back to global B

    def test_disabled_grading_passes_everything(self):
        g = grader(enabled=False, min_grade="B",
                   per_strategy_min_grade={"Almanac": "A++"})
        self.assertTrue(g.passes("C", "Almanac"))


if __name__ == "__main__":
    unittest.main()
