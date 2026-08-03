import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops.web.state_view import _news_block


class _Manager:
    def __init__(self, payload=None, raises=False):
        self.payload = payload
        self.raises = raises

    def snapshot(self, now=None):
        if self.raises:
            raise RuntimeError("news exploded")
        return self.payload


class _Controller:
    def __init__(self, manager=None):
        if manager is not None:
            self.news_manager = manager


class NewsBlockDegrades(unittest.TestCase):
    def test_missing_news_manager_is_unavailable(self):
        self.assertEqual(_news_block(_Controller()), {"status": "unavailable"})

    def test_snapshot_raising_is_unavailable(self):
        self.assertEqual(_news_block(_Controller(_Manager(raises=True))),
                         {"status": "unavailable"})

    def test_non_dict_snapshot_is_unavailable(self):
        self.assertEqual(_news_block(_Controller(_Manager(payload=["nope"]))),
                         {"status": "unavailable"})

    def test_none_snapshot_is_unavailable(self):
        self.assertEqual(_news_block(_Controller(_Manager(payload=None))),
                         {"status": "unavailable"})


class NewsBlockPassesThrough(unittest.TestCase):
    def test_valid_snapshot_is_returned_verbatim(self):
        payload = {"status": "ok", "cache_age_min": 12,
                   "next": {"title": "Core CPI m/m", "in_min": 47},
                   "blocked_symbols": {"GBPJPY": "BOE in 22m"}}
        self.assertEqual(_news_block(_Controller(_Manager(payload))), payload)


if __name__ == "__main__":
    unittest.main()
