"""Route-level tests for GET /api/equity and the recorder health counters."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from src.ops.equity_recorder import ensure_schema
from src.ops.web import auth, equity_view, server


class _Recorder:
    def __init__(self, conn, cfg=None):
        self.conn = conn
        self.counters = {"dropped_stale": 1, "dropped_invalid": 2,
                         "dropped_overflow": 3, "flush_errors": 4}
        self.cfg = cfg if cfg is not None else {
            "fine_cadence_s": equity_view.FINE_CADENCE_S,
            "coarse_bucket_s": equity_view.COARSE_CADENCE_S,
        }


class _Controller:
    def __init__(self, conn, cfg=None):
        self.equity_recorder = _Recorder(conn, cfg=cfg)


AUTH = {"Authorization": "Bearer sekret"}


def _client(conn, cfg=None):
    """Mirrors tests/unit/test_gui_server.py::_make — same env + throttle reset."""
    os.environ["TITAN_GUI_TOKEN"] = "sekret"
    os.environ.pop("TITAN_GUI_READONLY", None)
    auth.THROTTLE.reset()
    app = server.create_app(_Controller(conn, cfg=cfg), settings_store=None, bridge=None)
    return TestClient(app), AUTH


class EquityRoute(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        ensure_schema(self.conn)

    def test_requires_auth(self):
        client, _ = _client(self.conn)
        self.assertEqual(client.get("/api/equity").status_code, 401)

    def test_default_range_is_1d(self):
        client, hdr = _client(self.conn)
        body = client.get("/api/equity", headers=hdr).json()
        self.assertEqual(body["range"], "1d")
        self.assertEqual(body["tier"], "coarse")

    def test_known_range_is_honoured(self):
        client, hdr = _client(self.conn)
        body = client.get("/api/equity?range=15m", headers=hdr).json()
        self.assertEqual(body["range"], "15m")
        self.assertEqual(body["tier"], "fine")

    def test_unknown_range_falls_back_to_1d(self):
        client, hdr = _client(self.conn)
        body = client.get("/api/equity?range=nope", headers=hdr).json()
        self.assertEqual(body["range"], "1d")

    def test_empty_store_returns_empty_points_not_an_error(self):
        client, hdr = _client(self.conn)
        resp = client.get("/api/equity?range=1y", headers=hdr)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["points"], [])


class RangeValidation(unittest.TestCase):
    """(A) Missing/unknown-but-token-shaped ranges silently fall back to 1d
    with HTTP 200; structurally invalid range values are rejected 422.
    Rule: a valid range token is 1-8 chars of [A-Za-z0-9]. Anything else
    (too long, or containing characters outside that set) is malformed."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        ensure_schema(self.conn)

    def test_missing_range_falls_back_to_1d_200(self):
        client, hdr = _client(self.conn)
        resp = client.get("/api/equity", headers=hdr)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["range"], "1d")

    def test_unknown_token_shaped_range_falls_back_to_1d_200(self):
        client, hdr = _client(self.conn)
        resp = client.get("/api/equity?range=nope", headers=hdr)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["range"], "1d")

    def test_malformed_range_is_422(self):
        client, hdr = _client(self.conn)
        resp = client.get("/api/equity?range=" + "x" * 9, headers=hdr)
        self.assertEqual(resp.status_code, 422)

    def test_malformed_range_with_bad_chars_is_422(self):
        client, hdr = _client(self.conn)
        resp = client.get("/api/equity?range=1d;drop", headers=hdr)
        self.assertEqual(resp.status_code, 422)


class ConfigMismatchWarning(unittest.TestCase):
    """(B) The route must detect when the live recorder cfg's cadence values
    diverge from equity_view's module-level FINE_CADENCE_S/COARSE_CADENCE_S
    (which are frozen from equity_recorder._DEFAULTS at import time, not the
    operator's live config) and surface that as an explicit warning rather
    than silently mis-bucketing the chart."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        ensure_schema(self.conn)

    def test_mismatched_cfg_produces_warning(self):
        mismatched_cfg = {
            "fine_cadence_s": equity_view.FINE_CADENCE_S,
            "coarse_bucket_s": equity_view.COARSE_CADENCE_S + 300,
        }
        client, hdr = _client(self.conn, cfg=mismatched_cfg)
        body = client.get("/api/equity?range=1y", headers=hdr).json()
        self.assertIn("config_mismatch", body)
        self.assertEqual(body["config_mismatch"]["coarse_bucket_s"]["live"],
                          equity_view.COARSE_CADENCE_S + 300)
        self.assertEqual(body["config_mismatch"]["coarse_bucket_s"]["view"],
                          equity_view.COARSE_CADENCE_S)

    def test_matching_cfg_has_no_warning(self):
        client, hdr = _client(self.conn)
        body = client.get("/api/equity?range=1y", headers=hdr).json()
        self.assertNotIn("config_mismatch", body)


class HealthCounters(unittest.TestCase):
    def test_state_view_exposes_recorder_counters(self):
        from src.ops.web.state_view import _equity_recorder_health
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        c = _Controller(conn)
        self.assertEqual(_equity_recorder_health(c), {
            "dropped_stale": 1, "dropped_invalid": 2,
            "dropped_overflow": 3, "flush_errors": 4})

    def test_missing_recorder_reports_none_not_a_crash(self):
        from src.ops.web.state_view import _equity_recorder_health
        self.assertIsNone(_equity_recorder_health(object()))


if __name__ == "__main__":
    unittest.main()
