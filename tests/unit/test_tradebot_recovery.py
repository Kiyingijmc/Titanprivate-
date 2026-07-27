"""Unit tests for tradebot.core.recovery (M0-4).

Covers the boot sequence of docs/trading-bot-brainstorm/brainstorm-v2/
pass3-systems.md §1.3 — verify the chain, then project the newest snapshot plus
its tail — and the boot half of §1.4/F-015 (sole writer).

The five M0 corruption drills (pass8-synthesis.md:225a) are re-run here one
layer up from M0-3: S004 proved each of them makes ``EventLog.verify_chain()``
raise; these prove each of them makes the *boot* refuse, with no usable state.
That is the property that matters operationally, because "best-effort replay and
go is a forbidden code path" (pass3-systems.md:123).

The boot lock is deliberately a harder guarantee than M0-3's ``TestSoleWriter``:
those two cases prove that a second ``EventLog`` on the same file interleaves
*safely* under ``busy_timeout``; this proves a second *boot* is refused outright
and immediately. Both remain true, and one test here guards the fact that
``EventLog``'s own construction contract was not touched to get it.

NOTE ON LOCATION: this file lives directly under tests/unit/ (flat, like every
other test module here) rather than under tests/unit/tradebot/. A test package
named `tradebot` would shadow the real top-level `tradebot` package during
`unittest discover -s tests/unit`, so `import tradebot.core.recovery` would
resolve to the test package and every case here would error out. (Same
precedent as tests/unit/test_tradebot_events.py, S003/M0-2, and
tests/unit/test_tradebot_event_log.py, S004/M0-3.)
"""

import gzip
import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tradebot.core import projection, recovery
from tradebot.core.clock import SimClock
from tradebot.core.event_log import RECOVERY_REQUIRED, EventLog
from tradebot.core.events import canonical_json

# A fixed instant, so every chain in this module is byte-reproducible.
BASE_TS = int(datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc).timestamp()) * 1_000_000_000

CANDLE = "market.candle_closed"


def count_candles(state, envelope):
    bars = dict(state.get("bars") or {})
    instrument = envelope.payload["instrument"]
    bars[instrument] = bars.get(instrument, 0) + 1
    state["bars"] = bars
    return state


class RecoveryTestCase(unittest.TestCase):
    """Temp-dir plumbing plus a scoped reducer for the one schema used here."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "events.sqlite3"
        self.clock = SimClock(BASE_TS)

        scope = projection.reducer_scope()
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)
        projection.register_reducer(CANDLE)(count_candles)

    def make_log(self, db_path=None, clock=None, **kwargs):
        # SimClock never advances on its own, so sharing one instance across
        # logs keeps every chain in a test byte-reproducible.
        log = EventLog(db_path or self.db_path, clock or self.clock, **kwargs)
        self.addCleanup(log.close)
        return log

    def raw(self, db_path=None):
        """A second, plain connection — used to stage corruption."""
        conn = sqlite3.connect(str(db_path or self.db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    def append_n(self, log, count, *, start=0):
        return [
            log.append(
                CANDLE,
                1,
                BASE_TS + (start + i) * 1_000_000_000,
                "core",
                {"instrument": "EURUSD", "bar_index": start + i},
            )
            for i in range(count)
        ]

    def boot(self, log, **kwargs):
        result = recovery.verify_and_replay(log, **kwargs)
        self.addCleanup(result.release)
        return result

    def assert_recovery_required(self, result):
        self.assertEqual(result.status, RECOVERY_REQUIRED)
        self.assertTrue(result.recovery_required)
        self.assertFalse(result.ok)
        self.assertIsNone(result.state, "a refused boot must hand back no state at all")
        self.assertIsNone(result.chain_head)
        self.assertIn(RECOVERY_REQUIRED, result.reason or "")
        return result


class TestCleanBoot(RecoveryTestCase):
    def test_an_empty_log_boots_to_an_empty_projection(self):
        log = self.make_log()

        result = self.boot(log)

        self.assertEqual(result.status, recovery.OK)
        self.assertTrue(result.ok)
        self.assertEqual(result.state, {projection.LAST_SEQ: 0})
        self.assertEqual(result.chain_head, log.head())
        self.assertIsNone(result.snapshot_seq)

    def test_boot_without_a_snapshot_folds_the_whole_log(self):
        log = self.make_log()
        self.append_n(log, 4)

        result = self.boot(log)

        self.assertEqual(result.status, recovery.OK)
        self.assertEqual(result.state, {"bars": {"EURUSD": 4}, projection.LAST_SEQ: 4})
        self.assertEqual(result.chain_head, log.head())
        self.assertEqual(result.chain_head, log.verify_chain())
        self.assertIsNone(result.snapshot_seq)
        self.assertEqual(result.events_applied, 4)

    def test_boot_with_a_snapshot_folds_only_the_tail_on_top_of_it(self):
        log = self.make_log()
        self.append_n(log, 3)
        log.snapshot(projection.fold(log.read()))  # seq 4
        self.append_n(log, 2, start=3)             # seqs 5, 6

        result = self.boot(log)

        self.assertEqual(result.status, recovery.OK)
        self.assertEqual(result.state, {"bars": {"EURUSD": 5}, projection.LAST_SEQ: 6})
        self.assertEqual(result.chain_head, log.head())
        self.assertEqual(result.snapshot_seq, 4)
        # Only the two post-snapshot rows were replayed, not all six.
        self.assertEqual(result.events_applied, 2)

    def test_the_newest_snapshot_wins(self):
        log = self.make_log()
        self.append_n(log, 2)
        log.snapshot(projection.fold(log.read()))   # seq 3
        self.append_n(log, 2, start=2)              # seqs 4, 5
        log.snapshot(projection.fold(log.read()))   # seq 6
        self.append_n(log, 1, start=4)              # seq 7

        result = self.boot(log)

        self.assertEqual(result.snapshot_seq, 6)
        self.assertEqual(result.events_applied, 1)
        self.assertEqual(result.state, {"bars": {"EURUSD": 5}, projection.LAST_SEQ: 7})

    def test_a_snapshot_that_spilled_to_a_sidecar_still_seeds_the_boot(self):
        log = self.make_log(snapshot_inline_limit=1024)
        self.append_n(log, 2)
        log.snapshot({"blob": "x" * 4096, "bars": {"EURUSD": 2}})  # seq 3, spills
        self.append_n(log, 2, start=2)                             # seqs 4, 5
        self.assertTrue((self.tmp / "snapshots" / "3.json.gz").exists())

        result = self.boot(log)

        self.assertEqual(result.status, recovery.OK)
        self.assertEqual(result.state["blob"], "x" * 4096)
        self.assertEqual(result.state["bars"], {"EURUSD": 4})
        self.assertEqual(result.state[projection.LAST_SEQ], 5)

    def test_boot_survives_a_reopen_of_the_same_log(self):
        log = self.make_log()
        self.append_n(log, 3)
        first = self.boot(log)
        first.release()
        log.close()

        reopened = self.make_log()
        second = self.boot(reopened)

        self.assertEqual(second.state, first.state)
        self.assertEqual(second.chain_head, first.chain_head)


class TestCorruptionDrills(RecoveryTestCase):
    """The five M0 acceptance drills, at the boot layer."""

    def test_drill_1_truncated_tail_refuses_the_boot(self):
        log = self.make_log()
        self.append_n(log, 6)
        self.raw().execute("DELETE FROM events WHERE seq>4")

        result = self.assert_recovery_required(self.boot(log))

        self.assertIn("lost tail", result.reason)

    def test_drill_2_payload_bit_flip_refuses_the_boot(self):
        log = self.make_log()
        self.append_n(log, 6)
        row = self.raw().execute("SELECT payload FROM events WHERE seq=3").fetchone()
        tampered = json.loads(row["payload"])
        tampered["bar_index"] = 9999
        self.raw().execute(
            "UPDATE events SET payload=? WHERE seq=3", (json.dumps(tampered, sort_keys=True),)
        )

        result = self.assert_recovery_required(self.boot(log))

        self.assertIn("row_hash does not match", result.reason)

    def test_drill_3_row_hash_bit_flip_refuses_the_boot(self):
        log = self.make_log()
        self.append_n(log, 6)
        original = self.raw().execute("SELECT row_hash FROM events WHERE seq=3").fetchone()[0]
        flipped = ("1" if original[0] != "1" else "2") + original[1:]
        self.raw().execute("UPDATE events SET row_hash=? WHERE seq=3", (flipped,))

        self.assert_recovery_required(self.boot(log))

    def test_drill_4_deleted_row_refuses_the_boot(self):
        log = self.make_log()
        self.append_n(log, 6)
        self.raw().execute("DELETE FROM events WHERE seq=3")

        result = self.assert_recovery_required(self.boot(log))

        self.assertIn("seq gap", result.reason)

    def test_drill_5_corrupt_snapshot_sidecar_refuses_the_boot(self):
        log = self.make_log(snapshot_inline_limit=1024)
        self.append_n(log, 2)
        log.snapshot({"blob": "x" * 4096})  # seq 3, spills to a sidecar
        self.append_n(log, 2, start=2)
        sidecar = self.tmp / "snapshots" / "3.json.gz"
        original = sidecar.read_bytes()

        def assert_boot_refused():
            # Released straight away: each attempt takes the boot lock, and the
            # next one in this test would otherwise be turned away by its own
            # predecessor instead of by the corruption under test.
            result = self.boot(log)
            self.assert_recovery_required(result)
            result.release()

        # (a) valid gzip, different bytes.
        with gzip.open(sidecar, "wb") as handle:
            handle.write(b'{"blob": "tampered"}')
        assert_boot_refused()

        # (b) the compressed stream itself damaged.
        sidecar.write_bytes(original + b"\x00garbage-trailing-bytes\xff")
        assert_boot_refused()

        # (c) the sidecar gone entirely.
        sidecar.unlink()
        assert_boot_refused()

        # Restoring it makes the boot clean again — the drill proved the
        # sidecar, not some unrelated breakage.
        sidecar.write_bytes(original)
        healthy = self.boot(log)
        self.assertEqual(healthy.status, recovery.OK)
        self.assertEqual(healthy.chain_head, log.head())

    def test_no_drill_produces_a_usable_state(self):
        # The one property the whole §1.3 rule reduces to: a broken chain never
        # yields something the caller could mistake for a projection.
        log = self.make_log()
        self.append_n(log, 6)
        self.raw().execute("UPDATE events SET payload=? WHERE seq=2", ("{not json",))

        result = self.boot(log)

        self.assertIsNone(result.state)
        self.assertNotEqual(result.status, recovery.OK)


class TestDeterminism(RecoveryTestCase):
    def build(self, name):
        log = self.make_log(db_path=self.tmp / name / "events.sqlite3")
        self.append_n(log, 3)
        log.snapshot(projection.fold(log.read()))
        self.append_n(log, 2, start=3)
        return log

    def test_identical_streams_boot_to_identical_state_and_chain_head(self):
        first, second = self.build("a"), self.build("b")

        left, right = self.boot(first), self.boot(second)

        self.assertEqual(left.status, recovery.OK)
        self.assertEqual(right.status, recovery.OK)
        self.assertEqual(left.state, right.state)
        self.assertEqual(canonical_json(left.state), canonical_json(right.state))
        self.assertEqual(left.chain_head, right.chain_head)
        self.assertEqual(left.chain_head, first.head())
        self.assertEqual(right.chain_head, second.head())

    def test_a_differing_payload_diverges_both(self):
        first = self.build("a")
        second = self.make_log(db_path=self.tmp / "b" / "events.sqlite3")
        self.append_n(second, 3)
        second.snapshot(projection.fold(second.read()))
        second.append(CANDLE, 1, BASE_TS, "core", {"instrument": "XAUUSD", "bar_index": 3})

        left, right = self.boot(first), self.boot(second)

        self.assertNotEqual(left.state, right.state)
        self.assertNotEqual(left.chain_head, right.chain_head)


class TestBootLock(RecoveryTestCase):
    """F-015 at boot: one owner, refused immediately, not after a timeout."""

    #: Comfortably under EventLog's 5 s busy_timeout, so a pass here cannot be
    #: a SQLite contention wait wearing a lock's clothes.
    IMMEDIATE_S = 0.5

    def acquire(self, db_path=None):
        lock = recovery.acquire_boot_lock(db_path or self.db_path)
        self.addCleanup(lock.release)
        return lock

    def test_the_lock_file_sits_beside_the_db(self):
        lock = self.acquire()

        self.assertEqual(lock.path, self.tmp / "events.sqlite3.boot.lock")
        self.assertTrue(lock.path.exists())
        self.assertTrue(lock.held)

    def test_a_second_acquire_fails_immediately(self):
        self.acquire()

        started = time.monotonic()
        with self.assertRaises(recovery.BootLockUnavailable):
            recovery.acquire_boot_lock(self.db_path)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, self.IMMEDIATE_S, "the boot lock must refuse, not wait")

    def test_a_second_boot_is_refused_immediately_and_changes_nothing(self):
        log = self.make_log(busy_timeout_ms=5_000)
        self.append_n(log, 3)
        first = self.boot(log)
        self.assertTrue(first.ok)

        started = time.monotonic()
        with self.assertRaises(recovery.BootLockUnavailable):
            recovery.verify_and_replay(log)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, self.IMMEDIATE_S)
        # The refused boot neither corrupted nor double-wrote anything.
        self.assertEqual(log.count(), 3)
        self.assertEqual(log.verify_chain().seq, 3)
        self.assertEqual(log.head(), first.chain_head)

    def test_releasing_the_lock_lets_the_next_boot_in(self):
        log = self.make_log()
        self.append_n(log, 2)
        first = self.boot(log)
        first.release()

        second = self.boot(log)

        self.assertEqual(second.status, recovery.OK)
        self.assertEqual(second.state, first.state)

    def test_release_is_idempotent(self):
        lock = self.acquire()

        lock.release()
        lock.release()

        self.assertFalse(lock.held)

    def test_the_lock_is_a_context_manager(self):
        with recovery.acquire_boot_lock(self.db_path) as lock:
            self.assertTrue(lock.held)
        self.assertFalse(lock.held)
        # Freed, so the next owner gets it.
        self.acquire().release()

    def test_a_refused_boot_keeps_the_lock(self):
        # RECOVERY_REQUIRED still manages exits on existing positions, so this
        # process stays the log's sole owner and a second one must still be
        # turned away.
        log = self.make_log()
        self.append_n(log, 4)
        self.raw().execute("DELETE FROM events WHERE seq=2")

        refused = self.boot(log)

        self.assert_recovery_required(refused)
        self.assertIsNotNone(refused.lock)
        self.assertTrue(refused.lock.held)
        with self.assertRaises(recovery.BootLockUnavailable):
            recovery.acquire_boot_lock(self.db_path)

    def test_lock_false_takes_no_lock(self):
        log = self.make_log()
        self.append_n(log, 2)

        result = self.boot(log, lock=False)

        self.assertEqual(result.status, recovery.OK)
        self.assertIsNone(result.lock)
        self.assertFalse(recovery.boot_lock_path(self.db_path).exists())

    def test_the_boot_lock_does_not_change_the_event_log_contract(self):
        # The lock lives entirely in recovery.py. EventLog still constructs and
        # appends against a locked log exactly as M0-3's TestSoleWriter proves —
        # nothing in event_log.py was rewired to get the boot guarantee.
        log = self.make_log()
        self.append_n(log, 2)
        self.acquire()

        other = self.make_log()
        other.append(CANDLE, 1, BASE_TS, "core", {"instrument": "EURUSD", "bar_index": 99})

        self.assertEqual(other.count(), 3)
        self.assertEqual(other.verify_chain().seq, 3)


if __name__ == "__main__":
    unittest.main()
