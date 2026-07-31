"""Route-level tests for GET /api/equity and the recorder health counters."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from src.ops.equity_recorder import ensure_schema
from src.ops.web import auth, equity_view, server


class _Recorder:
    def __init__(self, conn, db_path=None, enabled=True):
        self.conn = conn
        self.db_path = db_path
        self.enabled = enabled
        self.buffer = []
        self.last_flush_ts = None
        self.counters = {"dropped_stale": 1, "dropped_invalid": 2,
                         "dropped_overflow": 3, "flush_errors": 4}


class _Controller:
    def __init__(self, conn, db_path=None, enabled=True):
        self.equity_recorder = _Recorder(conn, db_path=db_path, enabled=enabled)


class _NoRecorderController:
    pass


AUTH = {"Authorization": "Bearer sekret"}


def _app(controller):
    """Mirrors tests/unit/test_gui_server.py::_make — same env + throttle reset."""
    os.environ["TITAN_GUI_TOKEN"] = "sekret"
    os.environ.pop("TITAN_GUI_READONLY", None)
    auth.THROTTLE.reset()
    return TestClient(server.create_app(controller, settings_store=None, bridge=None)), AUTH


def _client(conn, db_path=None, enabled=True):
    return _app(_Controller(conn, db_path=db_path, enabled=enabled))


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


class _ExplodingConn:
    """Stands in for the recorder's WRITE connection. Any use is the bug."""

    def execute(self, *a, **k):
        raise AssertionError(
            "/api/equity read through the recorder's write connection — SQLite "
            "serialises per connection, so this stalls the asyncio trading loop")

    def close(self):
        raise AssertionError("/api/equity closed the recorder's write connection")


class ReadPathIsolation(unittest.TestCase):
    """C1(c): a file-backed recorder must be read through a SHORT-LIVED
    connection of the route's own, never the writer the trading loop uses."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "titan_core.db")
        self.now = time.time()
        seed = sqlite3.connect(self.path)
        ensure_schema(seed)
        base = int(self.now) // 300 * 300
        seed.executemany(
            "INSERT INTO equity_coarse "
            "(bucket_ts, equity, balance, peak, equity_min, equity_max) VALUES (?,?,?,?,?,?)",
            [(base - i * 300, 100.0 + i, 90.0, 200.0, 99.0, 101.0) for i in range(20)])
        seed.commit()
        seed.close()

    def test_route_serves_data_without_touching_the_write_connection(self):
        client, hdr = _client(_ExplodingConn(), db_path=self.path)
        resp = client.get("/api/equity?range=1d", headers=hdr)
        self.assertEqual(resp.status_code, 200)
        points = [p for p in resp.json()["points"] if p]
        self.assertEqual(len(points), 20)

    def test_read_connection_is_a_distinct_object_and_is_closed(self):
        rec = _Recorder(_ExplodingConn(), db_path=self.path)
        conn, owned = equity_view.read_connection(rec)
        self.assertTrue(owned)
        self.assertIsNot(conn, rec.conn)
        conn.close()

    def test_read_connection_cannot_write(self):
        """?mode=ro: a bug in the read path can never corrupt the live series."""
        rec = _Recorder(_ExplodingConn(), db_path=self.path)
        conn, _owned = equity_view.read_connection(rec)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM equity_coarse")
            conn.commit()
        conn.close()


class DisabledOrAbsentRecorder(unittest.TestCase):
    """M3: the fallback body must be the same contract as the live one."""

    def test_disabled_recorder_returns_a_resolved_range_and_real_bucket(self):
        client, hdr = _client(None, enabled=False)
        body = client.get("/api/equity?range=nope", headers=hdr).json()
        self.assertEqual(body["range"], "1d")            # resolved, not echoed
        self.assertEqual(body["tier"], "coarse")
        self.assertEqual(body["bucket_s"], 300)
        self.assertEqual(body["points"], [])

    def test_absent_recorder_matches_the_live_field_types(self):
        client, hdr = _app(_NoRecorderController())
        body = client.get("/api/equity?range=15m", headers=hdr).json()
        self.assertEqual(body["range"], "15m")
        self.assertEqual(body["tier"], "fine")
        self.assertEqual(body["bucket_s"], 10)
        self.assertEqual(body["series"], ["equity", "balance", "peak"])
        self.assertEqual(body["coverage"]["n"], 0)
        self.assertIsNone(body["coverage"]["first_sample_ts"])


class HealthCounters(unittest.TestCase):
    def test_state_view_exposes_counters_plus_liveness(self):
        from src.ops.web.state_view import _equity_recorder_health
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        health = _equity_recorder_health(_Controller(conn))
        self.assertEqual({k: health[k] for k in
                          ("dropped_stale", "dropped_invalid",
                           "dropped_overflow", "flush_errors")},
                         {"dropped_stale": 1, "dropped_invalid": 2,
                          "dropped_overflow": 3, "flush_errors": 4})
        self.assertTrue(health["enabled"])
        self.assertTrue(health["connected"])
        self.assertEqual(health["buffered"], 0)
        self.assertIsNone(health["last_flush_ts"])

    def test_self_disabled_recorder_is_distinguishable_from_a_healthy_one(self):
        """I2: four zero counters look IDENTICAL whether the recorder is fine or
        silently disabled itself at boot. The ledger tells the operator to check
        health.equity_recorder after a restart — that has to be answerable."""
        from src.ops.equity_recorder import EquityRecorder
        from src.ops.web.state_view import _equity_recorder_health

        tmp = tempfile.mkdtemp()
        blocker = os.path.join(tmp, "not_a_dir")
        with open(blocker, "w") as fh:
            fh.write("")
        broken = EquityRecorder(os.path.join(blocker, "core.db"), config={"enabled": True})
        healthy = EquityRecorder(os.path.join(tmp, "core.db"), config={"enabled": True})

        bad = _equity_recorder_health(type("C", (), {"equity_recorder": broken})())
        good = _equity_recorder_health(type("C", (), {"equity_recorder": healthy})())

        self.assertFalse(bad["enabled"])
        self.assertFalse(bad["connected"])
        self.assertTrue(good["enabled"])
        self.assertTrue(good["connected"])
        self.assertNotEqual(bad, good)

    def test_missing_recorder_reports_none_not_a_crash(self):
        from src.ops.web.state_view import _equity_recorder_health
        self.assertIsNone(_equity_recorder_health(object()))


if __name__ == "__main__":
    unittest.main()
