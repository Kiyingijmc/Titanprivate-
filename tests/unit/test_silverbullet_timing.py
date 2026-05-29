import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.strategies.models.silver_bullet import SilverBullet


class _Log:
    def log_event(self, *a, **k):
        pass


def sb(cfg):
    return SilverBullet(cfg, _Log())


class Timing(unittest.TestCase):
    def test_multi_window(self):
        s = sb({"windows": [[2, 4], [10, 11]]})
        self.assertTrue(s._in_window(2))
        self.assertTrue(s._in_window(3))
        self.assertFalse(s._in_window(4))   # end exclusive
        self.assertTrue(s._in_window(10))
        self.assertFalse(s._in_window(11))
        self.assertFalse(s._in_window(0))

    def test_legacy_session_ny_still_works(self):
        s = sb({"session_ny": ["10:00", "11:00"]})
        self.assertTrue(s._in_window(10))
        self.assertFalse(s._in_window(11))

    def test_string_windows_parse(self):
        s = sb({"windows": [["14:00", "16:00"]]})
        self.assertTrue(s._in_window(14))
        self.assertTrue(s._in_window(15))
        self.assertFalse(s._in_window(16))


if __name__ == "__main__":
    unittest.main()
