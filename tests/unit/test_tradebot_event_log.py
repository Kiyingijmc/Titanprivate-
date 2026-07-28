"""Unit tests for tradebot.core.event_log (M0-3).

Covers the F-004 integrity substrate from
docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md §1.3: the hash
chain, the five corruption drills, snapshot cadence + sidecars, archive,
backup/restore-verify, and sole-writer enforcement (§1.4/F-015).

The five drills are the M0 acceptance bar (pass8-synthesis.md:225a): truncate,
payload bit-flip, row_hash bit-flip, row delete, sidecar corrupt — each must
produce RECOVERY_REQUIRED, never a clean result.

Two of these cases are RS004 regression guards, both for defects a passing
suite did not catch: a restore proven with the live snapshots/ destroyed (the
backup must carry its own sidecars), and an archive retried after a crash
between the Parquet write and the SQLite delete (no duplicated rows).

NOTE ON LOCATION: this file lives directly under tests/unit/ (flat, like every
other test module here) rather than under tests/unit/tradebot/. A test package
named `tradebot` would shadow the real top-level `tradebot` package during
`unittest discover -s tests/unit`, so `import tradebot.core.event_log` would
resolve to the test package and every case here would error out. (Same
precedent as tests/unit/test_tradebot_events.py, S003/M0-2.)
"""

import gzip
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tradebot.core.clock import SimClock
from tradebot.core.events import canonical_json
from tradebot.core.event_log import (
    GENESIS_PREV_HASH,
    RECOVERY_REQUIRED,
    SNAPSHOT_BUNDLE_SUFFIX,
    SNAPSHOT_SCHEMA,
    BackupVerificationError,
    ChainHead,
    EventLog,
    RecoveryRequired,
    _write_parquet,
    compute_row_hash,
)

# A fixed instant so archive month-bucketing is deterministic.
BASE_TS = int(datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc).timestamp()) * 1_000_000_000
DAY_NS = 24 * 60 * 60 * 1_000_000_000


class EventLogTestCase(unittest.TestCase):
    """Shared temp-dir plumbing and a few small helpers."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "events.sqlite3"
        self.clock = SimClock(BASE_TS)

    def make_log(self, db_path=None, clock=None, **kwargs):
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
                "market.candle_closed",
                1,
                BASE_TS + (start + i) * 1_000_000_000,
                "core",
                {"instrument": "EURUSD", "bar_index": start + i},
            )
            for i in range(count)
        ]


class TestAppendAndChain(EventLogTestCase):
    def test_first_append_starts_a_gapless_chain_from_the_genesis_hash(self):
        log = self.make_log()
        envelope = log.append("market.tick", 1, BASE_TS, "core", {"bid": 1.1, "ask": 1.2})

        self.assertEqual(envelope.seq, 1)
        self.assertEqual(envelope.ts_ingest, BASE_TS)
        row = self.raw().execute("SELECT * FROM events WHERE seq=1").fetchone()
        self.assertEqual(row["prev_hash"], GENESIS_PREV_HASH)
        self.assertEqual(len(row["row_hash"]), 64)

    def test_seq_is_monotonic_and_prev_hash_links_every_row(self):
        log = self.make_log()
        self.append_n(log, 5)

        rows = self.raw().execute("SELECT * FROM events ORDER BY seq").fetchall()
        self.assertEqual([r["seq"] for r in rows], [1, 2, 3, 4, 5])
        for previous, row in zip(rows, rows[1:]):
            self.assertEqual(row["prev_hash"], previous["row_hash"])

    def test_row_hash_matches_the_documented_preimage(self):
        log = self.make_log()
        payload = {"instrument": "EURUSD", "bar_index": 0}
        log.append("market.candle_closed", 1, BASE_TS, "core", payload)

        row = self.raw().execute("SELECT * FROM events WHERE seq=1").fetchone()
        self.assertEqual(
            row["row_hash"],
            compute_row_hash(
                GENESIS_PREV_HASH, 1, "market.candle_closed", 1, BASE_TS, row["payload"]
            ),
        )

    def test_verify_chain_returns_the_head_of_a_clean_log(self):
        log = self.make_log()
        self.append_n(log, 4)

        head = log.verify_chain()
        self.assertEqual(head, log.head())
        self.assertEqual(head.seq, 4)

    def test_verify_chain_accepts_an_empty_log(self):
        log = self.make_log()
        self.assertEqual(log.verify_chain(), ChainHead(0, GENESIS_PREV_HASH))

    def test_events_round_trip_back_through_the_envelope(self):
        log = self.make_log()
        written = log.append(
            "signal.generated",
            2,
            BASE_TS,
            "child:sb",
            {"instrument": "XAUUSD", "direction": "LONG"},
            correlation_id="corr-1",
            parent_ids=("p1", "p2"),
        )

        (read_back,) = log.read()
        self.assertEqual(read_back.event_id, written.event_id)
        self.assertEqual(read_back.payload, {"instrument": "XAUUSD", "direction": "LONG"})
        self.assertEqual(read_back.parent_ids, ("p1", "p2"))
        self.assertEqual(read_back.correlation_id, "corr-1")
        self.assertEqual(read_back.seq, 1)

    def test_reopening_a_log_continues_the_same_chain(self):
        log = self.make_log()
        self.append_n(log, 3)
        head_before = log.head()
        log.close()

        reopened = self.make_log()
        self.assertEqual(reopened.head(), head_before)
        reopened.append("market.tick", 1, BASE_TS, "core", {"bid": 1.0, "ask": 1.1})
        self.assertEqual(reopened.verify_chain().seq, 4)


class TestIdempotency(EventLogTestCase):
    def test_repeat_idempotency_key_writes_no_row_and_is_counted(self):
        log = self.make_log()
        first = log.append(
            "exec.order_submitted", 1, BASE_TS, "exec", {"lots": 0.1},
            idempotency_key="client-key-1",
        )
        second = log.append(
            "exec.order_submitted", 1, BASE_TS + 5, "exec", {"lots": 0.9},
            idempotency_key="client-key-1",
        )

        self.assertEqual(log.count(), 1)
        self.assertEqual(log.dropped_duplicates, 1)
        self.assertEqual(second.seq, first.seq)
        self.assertEqual(second.event_id, first.event_id)
        self.assertEqual(second.payload, {"lots": 0.1})
        self.assertEqual(log.verify_chain().seq, 1)

    def test_distinct_keys_and_null_keys_all_append(self):
        log = self.make_log()
        log.append("exec.order_submitted", 1, BASE_TS, "exec", {"n": 1}, idempotency_key="a")
        log.append("exec.order_submitted", 1, BASE_TS, "exec", {"n": 2}, idempotency_key="b")
        log.append("market.tick", 1, BASE_TS, "core", {"n": 3})
        log.append("market.tick", 1, BASE_TS, "core", {"n": 4})

        self.assertEqual(log.count(), 4)
        self.assertEqual(log.dropped_duplicates, 0)


class TestDeterminism(EventLogTestCase):
    def test_identical_event_streams_produce_byte_identical_chain_heads(self):
        stream = [
            ("market.candle_closed", 1, BASE_TS + i, {"instrument": "EURUSD", "bar_index": i})
            for i in range(20)
        ]

        heads = []
        for index, start in enumerate((BASE_TS, BASE_TS + 999_999)):
            # Different clocks on purpose: ts_ingest must not enter the chain.
            log = self.make_log(
                db_path=self.tmp / f"det-{index}.sqlite3", clock=SimClock(start)
            )
            for schema, version, ts_event, payload in stream:
                log.append(schema, version, ts_event, "core", payload)
            heads.append(log.verify_chain())

        self.assertEqual(heads[0].row_hash, heads[1].row_hash)
        self.assertEqual(heads[0].seq, heads[1].seq)

    def test_a_differing_payload_diverges_the_chain_head(self):
        heads = []
        for index, last_payload in enumerate(({"n": 1}, {"n": 2})):
            log = self.make_log(db_path=self.tmp / f"div-{index}.sqlite3")
            log.append("market.tick", 1, BASE_TS, "core", {"n": 0})
            log.append("market.tick", 1, BASE_TS, "core", last_payload)
            heads.append(log.head().row_hash)

        self.assertNotEqual(heads[0], heads[1])


class TestCorruptionDrills(EventLogTestCase):
    """The five M0 acceptance drills (pass8-synthesis.md:225a)."""

    def assert_recovery_required(self, log, *, contains=None):
        with self.assertRaises(RecoveryRequired) as caught:
            log.verify_chain()
        self.assertEqual(caught.exception.status, RECOVERY_REQUIRED)
        self.assertIn("RECOVERY_REQUIRED", str(caught.exception))
        if contains:
            self.assertIn(contains, str(caught.exception))
        return caught.exception

    def test_drill_1_truncated_tail(self):
        log = self.make_log()
        self.append_n(log, 6)
        log.verify_chain()

        # A torn tail: the rows are gone, but the writer's head marker still
        # records how far the chain actually got.
        self.raw().execute("DELETE FROM events WHERE seq>4")

        self.assert_recovery_required(log, contains="lost tail")

    def test_drill_1b_truncated_tail_also_blocks_further_appends(self):
        log = self.make_log()
        self.append_n(log, 6)
        self.raw().execute("DELETE FROM events WHERE seq>4")

        with self.assertRaises(RecoveryRequired):
            log.append("market.tick", 1, BASE_TS, "core", {"bid": 1.0})

    def test_drill_2_payload_bit_flip(self):
        log = self.make_log()
        self.append_n(log, 6)

        row = self.raw().execute("SELECT payload FROM events WHERE seq=3").fetchone()
        tampered = json.loads(row["payload"])
        tampered["bar_index"] = 9999
        self.raw().execute(
            "UPDATE events SET payload=? WHERE seq=3", (json.dumps(tampered, sort_keys=True),)
        )

        self.assert_recovery_required(log, contains="row_hash does not match")

    def test_drill_3_row_hash_bit_flip(self):
        log = self.make_log()
        self.append_n(log, 6)

        original = self.raw().execute("SELECT row_hash FROM events WHERE seq=3").fetchone()[0]
        flipped = ("1" if original[0] != "1" else "2") + original[1:]
        self.raw().execute("UPDATE events SET row_hash=? WHERE seq=3", (flipped,))

        self.assert_recovery_required(log)

    def test_drill_4_deleted_middle_row(self):
        log = self.make_log()
        self.append_n(log, 6)

        self.raw().execute("DELETE FROM events WHERE seq=3")

        self.assert_recovery_required(log, contains="seq gap")

    def test_drill_4b_deleted_first_row(self):
        log = self.make_log()
        self.append_n(log, 6)

        self.raw().execute("DELETE FROM events WHERE seq=1")

        self.assert_recovery_required(log, contains="missing rows before seq 2")

    def test_drill_5_corrupt_snapshot_sidecar(self):
        log = self.make_log(snapshot_inline_limit=1024)
        self.append_n(log, 2)
        log.snapshot({"blob": "x" * 4096})
        self.append_n(log, 2, start=2)
        log.verify_chain()

        sidecar = self.tmp / "snapshots" / "3.json.gz"
        self.assertTrue(sidecar.exists())

        # (a) content replaced with a *valid* gzip of different bytes.
        original = sidecar.read_bytes()
        with gzip.open(sidecar, "wb") as handle:
            handle.write(b'{"blob": "tampered"}')
        self.assert_recovery_required(log, contains="sha256 mismatch")

        # (b) the compressed stream itself damaged.
        sidecar.write_bytes(original + b"\x00garbage-trailing-bytes\xff")
        self.assert_recovery_required(log)

        # (c) the sidecar gone entirely.
        sidecar.unlink()
        self.assert_recovery_required(log, contains="missing")

        # Restoring it makes the chain clean again — the drill proved the
        # sidecar, not some unrelated breakage.
        sidecar.write_bytes(original)
        self.assertEqual(log.verify_chain().seq, 5)

    def test_undecodable_payload_is_refused(self):
        log = self.make_log()
        self.append_n(log, 3)
        self.raw().execute("UPDATE events SET payload=? WHERE seq=2", ("{not json",))

        self.assert_recovery_required(log, contains="undecodable payload")

    def test_rewritten_actor_is_refused(self):
        """S009: `actor` is inside the pre-image, so rewriting *who* issued an
        event is detectable.

        Under the original six-field pre-image this row verified clean, which
        meant an attacker with write access to `events.sqlite3` could reassign
        any command to a different principal without breaking the chain — the
        exact provenance M2's command audit (pass3 §8.5) is built on.
        """
        log = self.make_log()
        self.append_n(log, 3)
        self.raw().execute("UPDATE events SET actor='tampered' WHERE seq=1")

        self.assert_recovery_required(log, contains="row_hash does not match")


class TestSnapshots(EventLogTestCase):
    def test_cadence_fires_on_the_event_count_threshold(self):
        log = self.make_log(snapshot_every=3, snapshot_payload={"kind": "synthetic"})
        self.append_n(log, 2)
        self.assertEqual(log.snapshot_seqs(), [])

        self.append_n(log, 1, start=2)
        self.assertEqual(log.snapshot_seqs(), [4])
        self.assertEqual(log.snapshots_written, 1)

    def test_snapshot_records_the_chain_head_it_was_taken_at(self):
        log = self.make_log(snapshot_every=3, snapshot_payload={"kind": "synthetic"})
        self.append_n(log, 3)

        (snapshot,) = [e for e in log.read() if e.schema == SNAPSHOT_SCHEMA]
        rows = self.raw().execute("SELECT * FROM events ORDER BY seq").fetchall()
        self.assertEqual(snapshot.payload["chain_head"]["seq"], 3)
        self.assertEqual(snapshot.payload["chain_head"]["row_hash"], rows[2]["row_hash"])
        # The snapshot row itself chains onto the head it cites.
        self.assertEqual(rows[3]["prev_hash"], snapshot.payload["chain_head"]["row_hash"])
        self.assertEqual(snapshot.payload["state"], {"kind": "synthetic"})

    def test_cadence_fires_on_the_24h_deadline(self):
        log = self.make_log(
            snapshot_every=1_000_000, snapshot_payload=lambda: {"kind": "callable"}
        )
        self.append_n(log, 1)
        self.assertEqual(log.snapshot_seqs(), [])

        self.clock.advance_by(DAY_NS)
        self.append_n(log, 1, start=1)

        self.assertEqual(log.snapshot_seqs(), [3])
        (snapshot,) = [e for e in log.read() if e.schema == SNAPSHOT_SCHEMA]
        self.assertEqual(snapshot.payload["state"], {"kind": "callable"})

    def test_a_fresh_log_is_not_immediately_due(self):
        log = self.make_log(snapshot_every=3, snapshot_payload={"kind": "synthetic"})
        self.assertFalse(log.snapshot_due())

    def test_large_payloads_spill_to_a_hashed_gzip_sidecar(self):
        log = self.make_log(snapshot_inline_limit=1024)
        self.append_n(log, 1)
        state = {"blob": "y" * 300_000}
        log.snapshot(state)

        (snapshot,) = [e for e in log.read() if e.schema == SNAPSHOT_SCHEMA]
        self.assertNotIn("state", snapshot.payload)
        sidecar = snapshot.payload["sidecar"]
        self.assertEqual(sidecar["path"], "snapshots/2.json.gz")

        path = self.tmp / "snapshots" / "2.json.gz"
        with gzip.open(path, "rb") as handle:
            raw = handle.read()
        self.assertEqual(json.loads(raw.decode("utf-8")), state)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sidecar["sha256"])
        self.assertEqual(sidecar["bytes"], len(raw))

        # verify_chain re-checks the sidecar hash, not just the row.
        self.assertEqual(log.verify_chain().seq, 2)

    def test_payloads_under_the_limit_stay_inline(self):
        log = self.make_log(snapshot_inline_limit=256 * 1024)
        log.snapshot({"blob": "z" * 1000})

        (snapshot,) = [e for e in log.read() if e.schema == SNAPSHOT_SCHEMA]
        self.assertIn("state", snapshot.payload)
        self.assertNotIn("sidecar", snapshot.payload)
        self.assertFalse((self.tmp / "snapshots").exists())


class TestArchive(EventLogTestCase):
    def build_archivable_log(self):
        log = self.make_log(snapshot_every=3, snapshot_payload={"kind": "synthetic"})
        self.append_n(log, 3)          # seq 1-3, snapshot at 4
        self.append_n(log, 3, start=3)  # seq 5-7, snapshot at 8
        self.append_n(log, 3, start=6)  # seq 9-11, snapshot at 12
        return log

    def build_history(self, db_name, marker):
        """An archivable log whose payloads carry `marker`, on its own DB file.

        Same seqs and same calendar month as any other history built this way,
        so both bucket into the same events-YYYYMM.parquet.
        """
        log = self.make_log(
            db_path=self.tmp / db_name,
            clock=SimClock(BASE_TS),
            snapshot_every=3,
            snapshot_payload={"kind": "synthetic"},
        )
        for i in range(9):
            log.append(
                "market.candle_closed",
                1,
                BASE_TS + i * 1_000_000_000,
                "core",
                {"instrument": "EURUSD", "bar_index": i, "history": marker},
            )
        return log

    def test_archive_refuses_when_the_target_file_holds_a_different_history(self):
        """RS004 MAJOR regression — a silent, unrecoverable data-loss path.

        `_write_parquet` deduped colliding seqs on `seq` ALONE, so a target file
        holding a *different* history at those seqs made every new row get
        filtered away — while `archive_before`'s DELETE removed them from SQLite
        regardless. The rows ended up in neither place, and the call reported
        success. Reachable whenever two logs share an archive dir — including the
        obvious operator response to RECOVERY_REQUIRED (move the broken DB aside
        and start fresh; `archive/` is a sibling of the DB and survives).

        A live chain and an archive that disagree at the same seq is exactly the
        "not provably intact" condition this module exists to announce.
        """
        shared_archive = self.tmp / "shared-archive"

        old = self.build_history("old.sqlite3", "OLD")
        old.archive_before(old.archive_eligible_seq(), archive_dir=shared_archive)

        new = self.build_history("new.sqlite3", "NEW")
        live_before = [e.seq for e in new.read()]

        with self.assertRaises(RecoveryRequired):
            new.archive_before(new.archive_eligible_seq(), archive_dir=shared_archive)

        # Nothing may have been deleted: refusing must leave the log intact.
        self.assertEqual([e.seq for e in new.read()], live_before)
        self.assertEqual(new.verify_chain().seq, live_before[-1])

    def test_archive_reports_how_many_rows_it_actually_wrote(self):
        """A no-op write must be distinguishable from a real archive.

        `rows` counts what was *offered*; a run that wrote nothing still
        reported a full archive, which is why the loss above was invisible to
        the caller. `rows_written` reports what actually reached Parquet.
        """
        log = self.build_archivable_log()
        result = log.archive_before(log.archive_eligible_seq())
        self.assertEqual(result["rows"], 7)
        self.assertEqual(result["rows_written"], 7)

        # Offering nothing writes nothing, and says so.
        target = Path(result["files"][0])
        self.assertEqual(
            _write_parquet(target, [], archived_at_ns=BASE_TS, source_db=str(log.db_path)),
            0,
        )

    def test_archive_boundary_is_the_second_newest_snapshot(self):
        log = self.build_archivable_log()
        self.assertEqual(log.snapshot_seqs(), [4, 8, 12])
        self.assertEqual(log.archive_eligible_seq(), 8)

    def test_archive_moves_old_events_to_parquet_and_keeps_the_chain_clean(self):
        import pyarrow.parquet as pq

        log = self.build_archivable_log()
        result = log.archive_before(log.archive_eligible_seq())

        self.assertEqual(result["rows"], 7)
        self.assertEqual(result["archived_through_seq"], 7)
        self.assertEqual([Path(p).name for p in result["files"]], ["events-202603.parquet"])

        table = pq.read_table(result["files"][0])
        self.assertEqual(table.num_rows, 7)
        self.assertEqual(table.column("seq").to_pylist(), [1, 2, 3, 4, 5, 6, 7])
        metadata = table.schema.metadata
        self.assertEqual(metadata[b"chain_first_seq"], b"1")
        self.assertEqual(metadata[b"chain_last_seq"], b"7")
        self.assertEqual(metadata[b"chain_first_prev_hash"].decode(), GENESIS_PREV_HASH)
        self.assertIn(b"chain_last_row_hash", metadata)
        self.assertIn(b"archived_at_ns", metadata)

        # The archived rows really left SQLite...
        self.assertEqual(log.count(), 5)
        self.assertEqual([e.seq for e in log.read()], [8, 9, 10, 11, 12])
        # ...and the retained chain still verifies, anchored on the retained
        # snapshot rather than on genesis.
        self.assertEqual(log.verify_chain().seq, 12)
        self.assertEqual(log.archived_through_seq(), 7)

    def test_chain_metadata_survives_a_round_trip_to_parquet(self):
        import pyarrow.parquet as pq

        log = self.build_archivable_log()
        rows_before = {
            row["seq"]: (row["row_hash"], row["prev_hash"])
            for row in self.raw().execute("SELECT * FROM events WHERE seq<8")
        }
        result = log.archive_before(8)

        table = pq.read_table(result["files"][0])
        seqs = table.column("seq").to_pylist()
        row_hashes = table.column("row_hash").to_pylist()
        prev_hashes = table.column("prev_hash").to_pylist()
        for seq, row_hash, prev_hash in zip(seqs, row_hashes, prev_hashes):
            self.assertEqual((row_hash, prev_hash), rows_before[seq])

    def test_appending_after_an_archive_keeps_the_chain_verifiable(self):
        log = self.build_archivable_log()
        log.archive_before(8)
        log.append("market.tick", 1, BASE_TS, "core", {"bid": 1.0})

        self.assertEqual(log.verify_chain().seq, 13)

    def test_archive_refuses_a_boundary_past_the_second_newest_snapshot(self):
        log = self.build_archivable_log()
        with self.assertRaises(ValueError):
            log.archive_before(12)

    def test_archive_refuses_a_seq_that_is_not_a_snapshot(self):
        log = self.build_archivable_log()
        with self.assertRaises(ValueError):
            log.archive_before(5)

    def test_archive_refuses_when_there_is_only_one_snapshot(self):
        log = self.make_log(snapshot_every=3, snapshot_payload={"kind": "synthetic"})
        self.append_n(log, 3)
        with self.assertRaises(ValueError):
            log.archive_before(4)

    def test_retry_after_a_crash_between_parquet_and_delete_does_not_duplicate(self):
        """RS004 MAJOR: the two steps are not one transaction.

        Reproduces the crash window exactly — step (a) wrote the month file,
        step (b)'s DELETE never committed — then lets the nightly job retry.
        """
        import pyarrow.parquet as pq

        log = self.build_archivable_log()
        rows = self.raw().execute(
            "SELECT * FROM events WHERE seq<8 ORDER BY seq ASC"
        ).fetchall()

        archive_dir = self.tmp / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        _write_parquet(
            archive_dir / "events-202603.parquet",
            rows,
            archived_at_ns=BASE_TS,
            source_db=str(self.db_path),
        )

        # SQLite still holds seq 1-7 and the chain still verifies, so the job
        # runs again with the same boundary.
        self.assertEqual(log.verify_chain().seq, 12)
        result = log.archive_before(8)

        table = pq.read_table(result["files"][0])
        self.assertEqual(table.column("seq").to_pylist(), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(table.schema.metadata[b"chain_last_seq"], b"7")

    def test_a_second_archive_still_appends_genuinely_new_rows(self):
        """Dedup must not turn into "never extend an existing month file"."""
        import pyarrow.parquet as pq

        log = self.build_archivable_log()
        first = log.archive_before(8)

        self.append_n(log, 3, start=9)   # seq 13-15, snapshot at 16
        self.append_n(log, 3, start=12)  # seq 17-19, snapshot at 20
        second = log.archive_before(16)

        self.assertEqual(first["files"], second["files"])
        table = pq.read_table(second["files"][0])
        self.assertEqual(table.column("seq").to_pylist(), list(range(1, 16)))
        self.assertEqual(table.schema.metadata[b"chain_last_seq"], b"15")

    def test_no_partial_parquet_file_is_left_behind(self):
        log = self.build_archivable_log()
        result = log.archive_before(8)

        leftovers = [p.name for p in Path(result["files"][0]).parent.iterdir()]
        self.assertEqual(leftovers, ["events-202603.parquet"])

    def test_archived_prefix_cannot_be_faked_by_deleting_rows(self):
        log = self.build_archivable_log()
        log.archive_before(8)
        # Deleting a row that was NOT archived still trips the gap check.
        self.raw().execute("DELETE FROM events WHERE seq=10")

        with self.assertRaises(RecoveryRequired):
            log.verify_chain()

    def test_archive_persists_the_archived_through_row_hash_in_log_meta(self):
        log = self.build_archivable_log()
        last_archived_row = self.raw().execute(
            "SELECT row_hash FROM events WHERE seq=7"
        ).fetchone()

        log.archive_before(8)

        meta_row = self.raw().execute(
            "SELECT value FROM log_meta WHERE key='archived_through_row_hash'"
        ).fetchone()
        self.assertIsNotNone(meta_row)
        self.assertEqual(meta_row["value"], last_archived_row["row_hash"])

    def test_verify_chain_catches_a_tampered_archived_through_row_hash(self):
        """RS004 MINOR regression — the archive/live seam was never hash-anchored.

        `verify_chain` previously anchored continuity across an archive on the
        ``archived_through`` *seq* watermark alone; it never checked the first
        retained row's ``prev_hash`` against the row that was actually
        archived. A mismatched or tampered boundary — the same
        disagreeing-history shape as
        `test_archive_refuses_when_the_target_file_holds_a_different_history`,
        but on the live side of the seam rather than the Parquet side — passed
        verification undetected. Tampering only ``archived_through_row_hash``
        (not any row) isolates that exact gap: every retained row is still
        internally self-consistent, so only the new boundary check can catch
        this.
        """
        log = self.build_archivable_log()
        log.archive_before(8)
        self.assertEqual(log.verify_chain().seq, 12)  # sanity: verifies before tampering

        self.raw().execute(
            "UPDATE log_meta SET value=? WHERE key='archived_through_row_hash'",
            (GENESIS_PREV_HASH,),
        )

        with self.assertRaises(RecoveryRequired):
            log.verify_chain()

    def test_verify_chain_requires_the_archived_through_row_hash_when_archived(self):
        """A log_meta row from before this fix (seq watermark, no hash) must
        not be silently trusted — the whole point is that a missing anchor is
        exactly as unproven as a wrong one."""
        log = self.build_archivable_log()
        log.archive_before(8)

        self.raw().execute("DELETE FROM log_meta WHERE key='archived_through_row_hash'")

        with self.assertRaises(RecoveryRequired):
            log.verify_chain()

    def test_write_parquet_refuses_new_rows_that_do_not_chain_from_the_stored_tail(self):
        """Same seam, checked on the Parquet side: rows offered as an
        extension to an existing archive file must actually chain from that
        file's ``chain_last_row_hash`` — not merely avoid colliding on
        ``seq``. A foreign row at a *new* seq (no collision, so the existing
        seq/row_hash dedup never sees it) previously slipped straight into
        the file.
        """
        log = self.build_archivable_log()
        result = log.archive_before(8)  # writes events-202603.parquet, seq 1-7
        target = Path(result["files"][0])

        seq = 8
        payload_json = canonical_json({"instrument": "EURUSD", "bar_index": seq})
        foreign_prev_hash = GENESIS_PREV_HASH  # does not chain from seq 7's row_hash
        foreign_row = {
            "seq": seq,
            "event_id": "evt-foreign-8",
            "schema": "market.candle_closed",
            "schema_version": 1,
            "ts_event": BASE_TS + seq * 1_000_000_000,
            "ts_ingest": BASE_TS + seq * 1_000_000_000,
            "correlation_id": None,
            "parent_ids": "[]",
            "idempotency_key": None,
            "actor": "core",
            "payload": payload_json,
            "prev_hash": foreign_prev_hash,
            "row_hash": compute_row_hash(
                foreign_prev_hash,
                seq,
                "market.candle_closed",
                1,
                BASE_TS + seq * 1_000_000_000,
                payload_json,
            ),
        }

        with self.assertRaises(RecoveryRequired):
            _write_parquet(
                target, [foreign_row], archived_at_ns=BASE_TS, source_db=str(log.db_path)
            )


class TestBackupAndRestore(EventLogTestCase):
    def build_log_with_a_sidecar(self):
        log = self.make_log(snapshot_inline_limit=1024)
        self.append_n(log, 3)
        log.snapshot({"blob": "b" * 4096})
        return log

    def test_good_backup_restores_and_verifies(self):
        log = self.build_log_with_a_sidecar()
        result = log.backup_and_verify(self.tmp / "backups")

        self.assertTrue(result["verified"])
        self.assertEqual(result["rows"], log.count())
        self.assertEqual(result["chain_head"], log.head())
        self.assertTrue(Path(result["archive"]).exists())
        self.assertTrue(Path(result["archive"]).name.endswith(".sqlite3.gz"))
        # Two artefacts, one backup: the DB dump and its sidecar bundle. The
        # uncompressed intermediate is not left lying around.
        self.assertEqual(
            sorted(p.name for p in (self.tmp / "backups").iterdir()),
            sorted([Path(result["archive"]).name, Path(result["snapshots_archive"]).name]),
        )
        self.assertTrue(Path(result["snapshots_archive"]).name.endswith(SNAPSHOT_BUNDLE_SUFFIX))
        self.assertEqual(result["sidecars"], 1)

    def test_backup_bundles_the_sidecars_it_references(self):
        log = self.build_log_with_a_sidecar()
        result = log.backup_and_verify(self.tmp / "backups")

        with tarfile.open(result["snapshots_archive"], "r:gz") as tar:
            names = sorted(tar.getnames())
        # Flat, by basename — the same name _verify_sidecar resolves.
        self.assertEqual(names, ["4.json.gz"])

    def test_restore_succeeds_with_the_live_snapshot_directory_destroyed(self):
        """The disaster this job exists for: the primary host is gone.

        Verification must prove the *archived* sidecars, so nothing may be read
        out of the still-present local snapshots/ directory (RS004 CRITICAL).
        """
        log = self.build_log_with_a_sidecar()
        archive = Path(log.backup_and_verify(self.tmp / "backups")["archive"])

        shutil.rmtree(self.tmp / "snapshots")

        result = log.verify_backup(archive)
        self.assertTrue(result["verified"])
        self.assertEqual(result["sidecars"], 1)

    def test_backup_missing_its_sidecar_bundle_fails_loudly(self):
        log = self.build_log_with_a_sidecar()
        result = log.backup_and_verify(self.tmp / "backups")
        Path(result["snapshots_archive"]).unlink()
        # The live sidecar is untouched: only a check that reads the *backup*
        # can notice, which is exactly the regression this guards.
        self.assertTrue((self.tmp / "snapshots" / "4.json.gz").exists())

        with self.assertRaises(BackupVerificationError) as caught:
            log.verify_backup(result["archive"])
        self.assertIn("sidecar missing", str(caught.exception))

    def test_backup_with_a_tampered_sidecar_in_the_bundle_fails_loudly(self):
        log = self.build_log_with_a_sidecar()
        result = log.backup_and_verify(self.tmp / "backups")

        bundle = Path(result["snapshots_archive"])
        tampered = self.tmp / "4.json.gz"
        with gzip.open(tampered, "wb") as handle:
            handle.write(b'{"blob": "tampered"}')
        with tarfile.open(bundle, "w:gz") as tar:
            tar.add(tampered, arcname="4.json.gz")

        with self.assertRaises(BackupVerificationError) as caught:
            log.verify_backup(result["archive"])
        self.assertIn("sha256 mismatch", str(caught.exception))

    def test_backup_with_a_damaged_sidecar_bundle_fails_loudly(self):
        log = self.build_log_with_a_sidecar()
        result = log.backup_and_verify(self.tmp / "backups")
        bundle = Path(result["snapshots_archive"])
        intact = bundle.read_bytes()

        # (a) not a readable container at all.
        bundle.write_bytes(b"this is not a tar.gz")
        with self.assertRaises(BackupVerificationError) as caught:
            log.verify_backup(result["archive"])
        self.assertIn("could not be read", str(caught.exception))

        # (b) the container truncated mid-stream — whether that surfaces as an
        # unreadable bundle or as a short sidecar that fails its hash, it must
        # never verify.
        bundle.write_bytes(intact[: len(intact) // 2])
        with self.assertRaises(BackupVerificationError):
            log.verify_backup(result["archive"])

        bundle.write_bytes(intact)
        self.assertTrue(log.verify_backup(result["archive"])["verified"])

    def test_a_log_with_no_sidecars_needs_no_bundle(self):
        log = self.make_log(snapshot_inline_limit=256 * 1024)
        self.append_n(log, 2)
        log.snapshot({"kind": "small"})

        result = log.backup_and_verify(self.tmp / "backups")
        self.assertTrue(result["verified"])
        self.assertEqual(result["sidecars"], 0)
        self.assertIsNone(result["snapshots_archive"])

    def test_backup_with_a_tampered_row_fails_loudly(self):
        log = self.build_log_with_a_sidecar()
        archive = Path(log.backup_and_verify(self.tmp / "backups")["archive"])

        self._rewrite_inside_archive(
            archive, "UPDATE events SET payload=? WHERE seq=2", ('{"tampered": true}',)
        )

        with self.assertRaises(BackupVerificationError) as caught:
            log.verify_backup(archive)
        self.assertIn(RECOVERY_REQUIRED, str(caught.exception))

    def test_backup_with_a_damaged_container_fails_loudly(self):
        log = self.build_log_with_a_sidecar()
        archive = Path(log.backup_and_verify(self.tmp / "backups")["archive"])

        archive.write_bytes(archive.read_bytes()[: len(archive.read_bytes()) // 2])

        with self.assertRaises(BackupVerificationError):
            log.verify_backup(archive)

    def test_backup_row_count_mismatch_fails_loudly(self):
        log = self.build_log_with_a_sidecar()
        archive = Path(log.backup_and_verify(self.tmp / "backups")["archive"])

        with self.assertRaises(BackupVerificationError):
            log.verify_backup(archive, expect_rows=log.count() + 1)

    def test_backing_up_a_log_whose_live_sidecar_is_corrupt_fails_loudly(self):
        """You cannot take a good backup of an already-broken log."""
        log = self.build_log_with_a_sidecar()

        with gzip.open(self.tmp / "snapshots" / "4.json.gz", "wb") as handle:
            handle.write(b'{"blob": "tampered"}')

        with self.assertRaises(BackupVerificationError) as caught:
            log.backup_and_verify(self.tmp / "backups")
        self.assertIn("sha256 mismatch", str(caught.exception))

    def _rewrite_inside_archive(self, archive, sql, params):
        """Decompress, tamper with the SQLite copy, recompress in place."""
        scratch = self.tmp / "scratch.sqlite3"
        with gzip.open(archive, "rb") as gz:
            scratch.write_bytes(gz.read())
        conn = sqlite3.connect(str(scratch), isolation_level=None)
        conn.execute(sql, params)
        # Fold any WAL back into the file before re-reading its bytes.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        with gzip.open(archive, "wb") as gz:
            gz.write(scratch.read_bytes())
        scratch.unlink()


class TestSoleWriter(EventLogTestCase):
    def test_append_fails_while_another_writer_holds_the_write_lock(self):
        log = self.make_log(busy_timeout_ms=150)
        self.append_n(log, 2)

        blocker = self.raw()
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute("INSERT INTO log_meta(key, value) VALUES('intruder', '1')")
        try:
            with self.assertRaises(sqlite3.OperationalError):
                log.append("market.tick", 1, BASE_TS, "core", {"bid": 1.0})
        finally:
            blocker.execute("ROLLBACK")

        # The rejected append left nothing behind.
        self.assertEqual(log.count(), 2)
        self.assertEqual(log.verify_chain().seq, 2)

    def test_a_second_event_log_never_interleaves_the_chain(self):
        first = self.make_log(busy_timeout_ms=500)
        second = self.make_log(busy_timeout_ms=500)

        for i in range(4):
            first.append("market.tick", 1, BASE_TS + i, "core", {"n": i, "w": "a"})
            second.append("market.tick", 1, BASE_TS + i, "core", {"n": i, "w": "b"})

        self.assertEqual(first.count(), 8)
        self.assertEqual([e.seq for e in first.read()], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(first.verify_chain().seq, 8)
        self.assertEqual(second.verify_chain(), first.verify_chain())


if __name__ == "__main__":
    unittest.main()
