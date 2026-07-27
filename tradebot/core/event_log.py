"""tradebot.core.event_log — sole-writer chained SQLite event log (M0-3).

Implements docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md §1.1
(the ``prev_hash``/``row_hash`` half of the envelope), §1.3 (F-004 integrity:
hash chain, snapshots, archive, backup + restore-verify) and §1.4 (F-015: the
core process is the *sole* writer).

The one rule this module exists to enforce: the log is either provably intact
or it says ``RECOVERY_REQUIRED``. "Best-effort replay and go" is a forbidden
code path (pass3-systems.md §1.3), so every integrity break — a ``seq`` gap, a
recomputed hash mismatch, a broken ``prev_hash`` link, an undecodable payload,
a lost tail, or a corrupt snapshot sidecar — raises :class:`RecoveryRequired`.
``core/recovery.py`` (M0-4) consumes that exact signal to drive the boot
sequence; this module only produces it.

Prior art: the WAL / pragma / persistent-connection discipline follows
``src/core/state_manager.py`` (pass3-systems.md:502) for *shape only* — nothing
here imports from ``src/``. Canonicalization is not reimplemented; it comes
from :mod:`tradebot.core.events`.

Scope notes (deliberate, M0-3):

* The ``RECOVERY_REQUIRED`` *operating mode* (refuse new trades, human ack)
  belongs to ``core/recovery.py``; here it is only a signal.
* Snapshot payloads are caller-supplied. Real projection content (open
  positions, ledger totals, feature-state manifest id) arrives with
  ``core/projection.py`` in M0-4.
* Sidecars and backups use stdlib ``gzip``/``tarfile`` rather than the ``zstd``
  named in the design doc, to avoid adding a third-party dependency at M0.
* ``backup_and_verify`` writes to a local ``dest_dir``; shipping the verified
  pair of artefacts off-box is an ops concern, not this module's. A backup is
  *two* files — ``events-<stamp>.sqlite3.gz`` and its
  ``events-<stamp>.snapshots.tar.gz`` sidecar bundle — and both must travel
  together, because ``verify_backup`` proves the archive against the bundle,
  never against the live snapshot directory.

Hash pre-image, recorded so nobody "fixes" a non-existent gap: ``row_hash``
covers exactly the six fields the design specifies (pass3-systems.md:30 —
``prev_hash ‖ seq ‖ schema ‖ schema_version ‖ ts_event ‖
canonical_json(payload)``), so this is spec-compliant. The consequence is that
``actor``, ``correlation_id``, ``parent_ids`` and ``idempotency_key`` are
stored but *not* chain-covered, so tampering with them is not detectable by
:meth:`EventLog.verify_chain`. Widening the pre-image would be a breaking
change to the hash format and a spec change owned by §1.1, not this session.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tradebot.core.clock import Clock
from tradebot.core.events import Envelope, canonical_json, envelope_from_dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The literal status token M0-4's recovery boot sequence switches on.
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

#: Genesis ``prev_hash``: 32 zero bytes, hex-encoded (pass3-systems.md §1.1).
GENESIS_PREV_HASH = "00" * 32

SNAPSHOT_SCHEMA = "snapshot.projection"
SNAPSHOT_SCHEMA_VERSION = 1

DEFAULT_SNAPSHOT_EVERY = 10_000
DEFAULT_SNAPSHOT_INTERVAL_NS = 24 * 60 * 60 * 1_000_000_000
DEFAULT_SNAPSHOT_INLINE_LIMIT = 256 * 1024
DEFAULT_BUSY_TIMEOUT_MS = 5_000

_META_HEAD_SEQ = "chain_head_seq"
_META_HEAD_HASH = "chain_head_hash"
_META_ARCHIVED_THROUGH = "archived_through_seq"
_META_LAST_SNAPSHOT_SEQ = "last_snapshot_seq"
_META_LAST_SNAPSHOT_TS = "last_snapshot_ts_ns"

# Field separator inside the hash pre-image. Without it, ("ab", "c") and
# ("a", "bc") would hash identically.
_FIELD_SEP = b"\x1f"

# gzip/zlib surface decompression damage through these three; EOFError is not
# an OSError, so it has to be named explicitly.
_DECOMPRESS_ERRORS = (OSError, EOFError, zlib.error)

# A damaged sidecar bundle can fail as a tar problem or as a gzip one.
_BUNDLE_ERRORS = (tarfile.TarError,) + _DECOMPRESS_ERRORS

#: Suffix of the sidecar bundle that travels with every ``.sqlite3.gz`` backup.
SNAPSHOT_BUNDLE_SUFFIX = ".snapshots.tar.gz"


# ---------------------------------------------------------------------------
# Errors + value objects
# ---------------------------------------------------------------------------


class RecoveryRequired(RuntimeError):
    """The chain is not provably intact — the log refuses to be trusted.

    Named literally after the ``RECOVERY_REQUIRED`` mode of pass3-systems.md
    §1.3; ``core/recovery.py`` (M0-4) turns this into refuse-new-trades +
    human-ack.
    """

    status = RECOVERY_REQUIRED

    def __init__(self, reason: str, *, seq: int | None = None) -> None:
        self.reason = reason
        self.seq = seq
        detail = f" (seq={seq})" if seq is not None else ""
        super().__init__(f"{RECOVERY_REQUIRED}: {reason}{detail}")


class BackupVerificationError(RuntimeError):
    """A backup could not be restored and proven intact.

    "An unverified backup is treated as no backup" (pass3-systems.md §1.3) —
    so this is raised, never logged-and-swallowed.
    """


@dataclass(frozen=True)
class ChainHead:
    """The verified tip of the chain."""

    seq: int
    row_hash: str


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def compute_row_hash(
    prev_hash: str,
    seq: int,
    schema: str,
    schema_version: int,
    ts_event: int,
    payload_json: str,
) -> str:
    """``SHA-256(prev_hash ‖ seq ‖ schema ‖ schema_version ‖ ts_event ‖ payload)``.

    ``prev_hash`` enters the pre-image as the raw 32 bytes it denotes (the
    design types it ``bytes32``); everything after it is UTF-8, separated by
    ``\\x1f``. ``payload_json`` must already be canonical JSON.
    """
    digest = hashlib.sha256()
    digest.update(bytes.fromhex(prev_hash))
    for part in (str(seq), schema, str(schema_version), str(ts_event), payload_json):
        digest.update(_FIELD_SEP)
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


_SCHEMA_DDL = (
    """
    CREATE TABLE IF NOT EXISTS events (
        seq             INTEGER PRIMARY KEY,
        event_id        TEXT    NOT NULL,
        "schema"        TEXT    NOT NULL,
        schema_version  INTEGER NOT NULL,
        ts_event        INTEGER NOT NULL,
        ts_ingest       INTEGER NOT NULL,
        correlation_id  TEXT,
        parent_ids      TEXT    NOT NULL,
        idempotency_key TEXT,
        actor           TEXT    NOT NULL,
        payload         TEXT    NOT NULL,
        prev_hash       TEXT    NOT NULL,
        row_hash        TEXT    NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idempotency
        ON events(idempotency_key) WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_schema_seq ON events("schema", seq)
    """,
    """
    CREATE TABLE IF NOT EXISTS log_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)

_EVENT_COLUMNS = (
    "seq",
    "event_id",
    "schema",
    "schema_version",
    "ts_event",
    "ts_ingest",
    "correlation_id",
    "parent_ids",
    "idempotency_key",
    "actor",
    "payload",
    "prev_hash",
    "row_hash",
)

_SELECT_ALL = 'SELECT seq, event_id, "schema", schema_version, ts_event, ts_ingest, ' \
    "correlation_id, parent_ids, idempotency_key, actor, payload, prev_hash, row_hash FROM events"


class EventLog:
    """Sole-writer, hash-chained SQLite event log.

    One process owns the write path (F-015). ``busy_timeout`` is still set
    defensively, so a second writer that shows up anyway blocks and then fails
    loudly instead of silently interleaving.
    """

    def __init__(
        self,
        db_path: str | os.PathLike[str],
        clock: Clock,
        *,
        snapshot_payload: dict | Callable[[], dict] | None = None,
        snapshot_every: int = DEFAULT_SNAPSHOT_EVERY,
        snapshot_interval_ns: int = DEFAULT_SNAPSHOT_INTERVAL_NS,
        snapshot_dir: str | os.PathLike[str] | None = None,
        snapshot_inline_limit: int = DEFAULT_SNAPSHOT_INLINE_LIMIT,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._clock = clock
        self._snapshot_payload = snapshot_payload
        self._snapshot_every = int(snapshot_every)
        self._snapshot_interval_ns = int(snapshot_interval_ns)
        self._snapshot_dir = (
            Path(snapshot_dir) if snapshot_dir is not None else self.db_path.parent / "snapshots"
        )
        self._inline_limit = int(snapshot_inline_limit)
        self._busy_timeout_ms = int(busy_timeout_ms)

        # RLock, not Lock: snapshot() re-enters append() through the same lock.
        self._lock = threading.RLock()
        self._in_snapshot = False

        self.appended = 0
        self.dropped_duplicates = 0
        self.snapshots_written = 0

        # isolation_level=None -> autocommit; transactions are opened by hand
        # with BEGIN IMMEDIATE so the write lock is taken up front rather than
        # on first write (which is what makes contention deterministic).
        self._conn = sqlite3.connect(
            str(self.db_path), isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        for statement in _SCHEMA_DDL:
            self._conn.execute(statement)

        self._head = ChainHead(0, GENESIS_PREV_HASH)
        self._archived_through = 0
        self._last_snapshot_seq = 0
        self._last_snapshot_ts = self._clock.now_ns()
        self._reload_state()

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.DatabaseError:
                    # A checkpoint failure on close must not mask the real
                    # error that is usually already on its way up.
                    pass
                self._conn.close()
                self._conn = None  # type: ignore[assignment]

    def checkpoint(self) -> None:
        """Fold the WAL back into the main DB file (§1.3 growth control)."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # -- meta / head -------------------------------------------------------

    def _meta_get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM log_meta WHERE key=?", (key,)).fetchone()
        return None if row is None else row["value"]

    def _meta_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO log_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def _marker(self) -> ChainHead:
        """The head as the writer last recorded it, independent of the rows.

        This is what makes a lost tail detectable: rows can vanish, but the
        marker still says how far the chain got.
        """
        seq = self._meta_get(_META_HEAD_SEQ)
        row_hash = self._meta_get(_META_HEAD_HASH)
        if seq is None or row_hash is None:
            return ChainHead(0, GENESIS_PREV_HASH)
        return ChainHead(int(seq), row_hash)

    def _last_row(self) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT seq, row_hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()

    def _reload_state(self) -> None:
        marker = self._marker()
        row = self._last_row()
        self._head = ChainHead(row["seq"], row["row_hash"]) if row is not None else marker
        self._archived_through = int(self._meta_get(_META_ARCHIVED_THROUGH) or 0)

        snap_seq = self._meta_get(_META_LAST_SNAPSHOT_SEQ)
        if snap_seq is None:
            snap_row = self._conn.execute(
                'SELECT seq FROM events WHERE "schema"=? ORDER BY seq DESC LIMIT 1',
                (SNAPSHOT_SCHEMA,),
            ).fetchone()
            self._last_snapshot_seq = snap_row["seq"] if snap_row else self._archived_through
        else:
            self._last_snapshot_seq = int(snap_seq)

        snap_ts = self._meta_get(_META_LAST_SNAPSHOT_TS)
        if snap_ts is not None:
            self._last_snapshot_ts = int(snap_ts)
        else:
            first = self._conn.execute(
                "SELECT ts_ingest FROM events ORDER BY seq ASC LIMIT 1"
            ).fetchone()
            # A fresh log starts its 24 h clock now, so opening one does not
            # immediately look overdue for a snapshot.
            self._last_snapshot_ts = first["ts_ingest"] if first else self._clock.now_ns()

    def head(self) -> ChainHead:
        """The current chain head as this instance last saw it."""
        with self._lock:
            return self._head

    def count(self) -> int:
        """Rows retained in SQLite (archived rows are not counted)."""
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def archived_through_seq(self) -> int:
        with self._lock:
            return self._archived_through

    def stats(self) -> dict:
        with self._lock:
            return {
                "appended": self.appended,
                "dropped_duplicates": self.dropped_duplicates,
                "snapshots_written": self.snapshots_written,
                "head_seq": self._head.seq,
                "archived_through_seq": self._archived_through,
            }

    # -- append ------------------------------------------------------------

    def append(
        self,
        schema: str,
        schema_version: int,
        ts_event: int,
        actor: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        parent_ids: tuple[str, ...] = (),
        idempotency_key: str | None = None,
    ) -> Envelope:
        """Append one event in a single transaction, extending the hash chain.

        Returns the stored :class:`~tradebot.core.events.Envelope`. A repeat
        of an ``idempotency_key`` already in the log writes nothing, bumps
        :attr:`dropped_duplicates`, and returns the *original* envelope — a
        duplicate is a no-op, never an error (§1.1).
        """
        with self._lock:
            envelope = self._append_locked(
                schema,
                schema_version,
                ts_event,
                actor,
                payload,
                correlation_id=correlation_id,
                parent_ids=parent_ids,
                idempotency_key=idempotency_key,
            )
            if not self._in_snapshot:
                self._maybe_snapshot_locked()
            return envelope

    def _append_locked(
        self,
        schema: str,
        schema_version: int,
        ts_event: int,
        actor: str,
        payload: dict,
        *,
        correlation_id: str | None,
        parent_ids: tuple[str, ...],
        idempotency_key: str | None,
    ) -> Envelope:
        payload_json = canonical_json(payload)
        parents = list(parent_ids)

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if idempotency_key is not None:
                existing = self._conn.execute(
                    f"{_SELECT_ALL} WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if existing is not None:
                    self._conn.execute("ROLLBACK")
                    self.dropped_duplicates += 1
                    return _row_to_envelope(existing)

            marker = self._marker()
            last = self._last_row()
            if last is None:
                head = marker
            else:
                head = ChainHead(last["seq"], last["row_hash"])
                if marker.seq > head.seq:
                    # The writer got further than the rows that survive: the
                    # tail was lost. Appending now would reuse seq numbers.
                    self._conn.execute("ROLLBACK")
                    raise RecoveryRequired(
                        "chain head marker is ahead of the last retained row (lost tail)",
                        seq=marker.seq,
                    )

            seq = head.seq + 1
            ts_ingest = self._clock.now_ns()
            envelope = Envelope(
                schema=schema,
                schema_version=schema_version,
                ts_event=ts_event,
                ts_ingest=ts_ingest,
                actor=actor,
                payload=payload,
                correlation_id=correlation_id,
                parent_ids=tuple(parents),
                idempotency_key=idempotency_key,
                seq=seq,
            )
            row_hash = compute_row_hash(
                head.row_hash, seq, schema, schema_version, ts_event, payload_json
            )
            self._conn.execute(
                'INSERT INTO events(seq, event_id, "schema", schema_version, ts_event, '
                "ts_ingest, correlation_id, parent_ids, idempotency_key, actor, payload, "
                "prev_hash, row_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    seq,
                    envelope.event_id,
                    schema,
                    schema_version,
                    ts_event,
                    ts_ingest,
                    correlation_id,
                    json.dumps(parents),
                    idempotency_key,
                    actor,
                    payload_json,
                    head.row_hash,
                    row_hash,
                ),
            )
            self._meta_set(_META_HEAD_SEQ, str(seq))
            self._meta_set(_META_HEAD_HASH, row_hash)
            self._conn.execute("COMMIT")
        except BaseException:
            # ROLLBACK on an already-rolled-back connection is itself an
            # error; swallow only that, never the original exception.
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise

        self._head = ChainHead(seq, row_hash)
        self.appended += 1
        return envelope

    # -- read --------------------------------------------------------------

    def read(self, from_seq: int = 0, to_seq: int | None = None) -> list[Envelope]:
        """Retained events with ``from_seq <= seq <= to_seq``, in seq order."""
        with self._lock:
            if to_seq is None:
                rows = self._conn.execute(
                    f"{_SELECT_ALL} WHERE seq>=? ORDER BY seq ASC", (from_seq,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    f"{_SELECT_ALL} WHERE seq>=? AND seq<=? ORDER BY seq ASC",
                    (from_seq, to_seq),
                ).fetchall()
            return [_row_to_envelope(row) for row in rows]

    def snapshot_seqs(self) -> list[int]:
        """Seqs of the retained ``snapshot.projection`` rows, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                'SELECT seq FROM events WHERE "schema"=? ORDER BY seq ASC', (SNAPSHOT_SCHEMA,)
            ).fetchall()
            return [row["seq"] for row in rows]

    # -- verification ------------------------------------------------------

    def verify_chain(self, from_seq: int = 0) -> ChainHead:
        """Walk the chain; return the verified head or refuse.

        Checks, in order: no missing rows (gapless ``seq``, front honoured
        against the archive watermark), decodable payloads, ``row_hash``
        recomputes, ``prev_hash`` continuity, every referenced snapshot
        sidecar still hashes, and the tail reaches the recorded head marker.

        Raises :class:`RecoveryRequired` on any break.
        """
        with self._lock:
            try:
                rows = self._conn.execute(
                    'SELECT seq, "schema", schema_version, ts_event, payload, prev_hash, '
                    "row_hash FROM events WHERE seq>=? ORDER BY seq ASC",
                    (from_seq,),
                ).fetchall()
                marker = self._marker()
                archived_through = int(self._meta_get(_META_ARCHIVED_THROUGH) or 0)
            except sqlite3.DatabaseError as exc:
                raise RecoveryRequired(f"event log is unreadable: {exc}") from exc

            if not rows:
                if marker.seq > archived_through and from_seq <= marker.seq:
                    raise RecoveryRequired(
                        "chain head marker recorded but no events retained", seq=marker.seq
                    )
                return marker

            expected_first = max(from_seq, archived_through + 1)
            previous: sqlite3.Row | None = None

            for row in rows:
                seq = row["seq"]
                if previous is None:
                    if seq != expected_first:
                        raise RecoveryRequired(
                            f"missing rows before seq {seq} (expected first seq {expected_first})",
                            seq=seq,
                        )
                    if seq == 1 and row["prev_hash"] != GENESIS_PREV_HASH:
                        raise RecoveryRequired("genesis row prev_hash is not zero", seq=seq)
                else:
                    if seq != previous["seq"] + 1:
                        raise RecoveryRequired(
                            f"seq gap between {previous['seq']} and {seq}", seq=seq
                        )
                    if row["prev_hash"] != previous["row_hash"]:
                        raise RecoveryRequired("prev_hash does not link to the prior row", seq=seq)

                payload_json = row["payload"]
                try:
                    payload = json.loads(payload_json)
                except (TypeError, ValueError) as exc:
                    raise RecoveryRequired(f"undecodable payload: {exc}", seq=seq) from exc

                try:
                    expected_hash = compute_row_hash(
                        row["prev_hash"],
                        seq,
                        row["schema"],
                        row["schema_version"],
                        row["ts_event"],
                        payload_json,
                    )
                except ValueError as exc:
                    raise RecoveryRequired(f"malformed prev_hash: {exc}", seq=seq) from exc

                if expected_hash != row["row_hash"]:
                    raise RecoveryRequired("row_hash does not match the row contents", seq=seq)

                if row["schema"] == SNAPSHOT_SCHEMA:
                    self._verify_sidecar(payload, seq)

                previous = row

            assert previous is not None  # non-empty rows
            if previous["seq"] != marker.seq or previous["row_hash"] != marker.row_hash:
                raise RecoveryRequired(
                    f"chain tail ends at seq {previous['seq']} but the recorded head is "
                    f"seq {marker.seq} (lost tail)",
                    seq=previous["seq"],
                )

            return ChainHead(previous["seq"], previous["row_hash"])

    def _verify_sidecar(self, payload: dict, seq: int) -> None:
        sidecar = payload.get("sidecar") if isinstance(payload, dict) else None
        if not sidecar:
            return
        # Resolved by basename inside *this instance's* snapshot dir. A probe
        # opened on a restored backup is given the sidecars extracted from that
        # backup's own bundle, so it never reads the live directory.
        path = self._snapshot_dir / Path(str(sidecar.get("path", ""))).name
        if not path.exists():
            raise RecoveryRequired(f"snapshot sidecar missing: {path}", seq=seq)
        try:
            with gzip.open(path, "rb") as handle:
                raw = handle.read()
        except _DECOMPRESS_ERRORS as exc:
            raise RecoveryRequired(f"snapshot sidecar unreadable: {exc}", seq=seq) from exc
        if hashlib.sha256(raw).hexdigest() != sidecar.get("sha256"):
            raise RecoveryRequired("snapshot sidecar sha256 mismatch", seq=seq)

    # -- snapshots ---------------------------------------------------------

    def snapshot_due(self) -> bool:
        """True once 10 000 events or 24 h have passed, whichever first."""
        with self._lock:
            events_since = self._head.seq - self._last_snapshot_seq
            elapsed = self._clock.now_ns() - self._last_snapshot_ts
            return events_since >= self._snapshot_every or elapsed >= self._snapshot_interval_ns

    def snapshot(
        self,
        payload: dict | Callable[[], dict] | None = None,
        *,
        actor: str = "core",
        ts_event: int | None = None,
    ) -> Envelope:
        """Append a ``snapshot.projection`` event now, cadence notwithstanding.

        ``payload`` (or the constructor's ``snapshot_payload``) may be a dict
        or a zero-arg callable. Anything larger than ``snapshot_inline_limit``
        spills to ``snapshots/<seq>.json.gz`` with its SHA-256 recorded in the
        event, so the chain covers the sidecar.
        """
        with self._lock:
            return self._snapshot_locked(payload, actor=actor, ts_event=ts_event)

    def _maybe_snapshot_locked(self) -> Envelope | None:
        if self._snapshot_payload is None or not self.snapshot_due():
            return None
        return self._snapshot_locked(None, actor="core", ts_event=None)

    def _snapshot_locked(
        self,
        payload: dict | Callable[[], dict] | None,
        *,
        actor: str,
        ts_event: int | None,
    ) -> Envelope:
        provider = self._snapshot_payload if payload is None else payload
        state = provider() if callable(provider) else provider
        if state is None:
            state = {}

        head = self._head
        body: dict[str, Any] = {"chain_head": {"seq": head.seq, "row_hash": head.row_hash}}

        state_json = canonical_json(state)
        raw = state_json.encode("utf-8")
        if len(raw) > self._inline_limit:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
            path = self._snapshot_dir / f"{head.seq + 1}.json.gz"
            with open(path, "wb") as handle:
                # mtime=0 keeps the sidecar bytes reproducible.
                with gzip.GzipFile(fileobj=handle, mode="wb", mtime=0) as gz:
                    gz.write(raw)
            body["sidecar"] = {
                "path": _relative_path(path, self.db_path.parent),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        else:
            body["state"] = state

        self._in_snapshot = True
        try:
            envelope = self._append_locked(
                SNAPSHOT_SCHEMA,
                SNAPSHOT_SCHEMA_VERSION,
                ts_event if ts_event is not None else self._clock.now_ns(),
                actor,
                body,
                correlation_id=None,
                parent_ids=(),
                idempotency_key=None,
            )
        finally:
            self._in_snapshot = False

        self._last_snapshot_seq = int(envelope.seq or 0)
        self._last_snapshot_ts = self._clock.now_ns()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._meta_set(_META_LAST_SNAPSHOT_SEQ, str(self._last_snapshot_seq))
            self._meta_set(_META_LAST_SNAPSHOT_TS, str(self._last_snapshot_ts))
            self._conn.execute("COMMIT")
        except BaseException:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        self.snapshots_written += 1
        return envelope

    # -- archive -----------------------------------------------------------

    def archive_eligible_seq(self) -> int | None:
        """Seq of the second-newest snapshot — the archive boundary (§1.3).

        Events older than it may leave SQLite; the newest snapshot plus its
        tail always stay, so replay is never longer than one snapshot period.
        """
        seqs = self.snapshot_seqs()
        return seqs[-2] if len(seqs) >= 2 else None

    def archive_before(
        self, snapshot_seq: int, *, archive_dir: str | os.PathLike[str] | None = None
    ) -> dict:
        """Export events with ``seq < snapshot_seq`` to Parquet, then drop them.

        ``snapshot_seq`` must name a retained snapshot at or before
        :meth:`archive_eligible_seq` — archiving past the second-newest
        snapshot would delete the events the retained snapshot needs.

        The Parquet write and the SQLite delete cannot share a transaction, so
        a crash between them leaves the rows archived *and* still live. That is
        safe to retry: nothing was deleted, the chain still verifies, and
        :func:`_write_parquet` drops rows already present in the target file
        rather than duplicating them — but only when the stored ``row_hash``
        matches. A colliding ``seq`` with a *different* hash means the live
        chain and the archive disagree, and raises :class:`RecoveryRequired`
        before anything is deleted.

        Returns ``rows`` (offered) and ``rows_written`` (actually archived);
        they differ on a retry, and only the second proves work was done.
        """
        with self._lock:
            self.verify_chain()  # only a *verified* chain may be archived

            snapshots = self.snapshot_seqs()
            if snapshot_seq not in snapshots:
                raise ValueError(f"seq {snapshot_seq} is not a retained {SNAPSHOT_SCHEMA} event")
            eligible = self.archive_eligible_seq()
            if eligible is None:
                raise ValueError(
                    "archiving needs at least two snapshots; the second-newest is the boundary"
                )
            if snapshot_seq > eligible:
                raise ValueError(
                    f"refusing to archive at seq {snapshot_seq}: the second-newest snapshot "
                    f"is seq {eligible}"
                )

            target_dir = (
                Path(archive_dir) if archive_dir is not None else self.db_path.parent / "archive"
            )
            rows = self._conn.execute(
                f"{_SELECT_ALL} WHERE seq<? ORDER BY seq ASC", (snapshot_seq,)
            ).fetchall()
            if not rows:
                return {
                    "rows": 0,
                    "rows_written": 0,
                    "files": [],
                    "archived_through_seq": self._archived_through,
                }

            target_dir.mkdir(parents=True, exist_ok=True)
            by_month: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                by_month.setdefault(_month_key(row["ts_event"]), []).append(row)

            files = []
            rows_written = 0
            for month, month_rows in sorted(by_month.items()):
                path = target_dir / f"events-{month}.parquet"
                # Raises RecoveryRequired if the target already holds a
                # *different* event at any of these seqs — the DELETE below is
                # unconditional, so a silent drop there would lose the rows.
                rows_written += _write_parquet(
                    path, month_rows, archived_at_ns=self._clock.now_ns(),
                    source_db=str(self.db_path),
                )
                files.append(str(path))

            archived_through = rows[-1]["seq"]
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM events WHERE seq<?", (snapshot_seq,))
                self._meta_set(_META_ARCHIVED_THROUGH, str(archived_through))
                self._conn.execute("COMMIT")
            except BaseException:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise
            self._archived_through = archived_through
            self.checkpoint()

            return {
                "rows": len(rows),           # offered
                "rows_written": rows_written,  # actually reached Parquet
                "files": files,
                "archived_through_seq": archived_through,
            }

    # -- backup ------------------------------------------------------------

    def backup_and_verify(self, dest_dir: str | os.PathLike[str]) -> dict:
        """``VACUUM INTO`` a dated copy, bundle its sidecars, then prove both.

        Two artefacts are produced and they are one backup:
        ``events-<stamp>.sqlite3.gz`` and ``events-<stamp>.snapshots.tar.gz``
        (the snapshot sidecar payloads the chain references). Shipping only the
        first off-box would leave every spilled snapshot unreconstructable, so
        :meth:`verify_backup` proves the pair — never the live snapshot
        directory.

        The verification is not optional: an archive that will not restore, or
        that restores to a chain that does not verify, raises
        :class:`BackupVerificationError`. Unverified backup = no backup.
        """
        with self._lock:
            dest = Path(dest_dir)
            dest.mkdir(parents=True, exist_ok=True)
            self.checkpoint()

            stamp = datetime.fromtimestamp(
                self._clock.now_ns() // 1_000_000_000, timezone.utc
            ).strftime("%Y%m%dT%H%M%SZ")
            plain = dest / f"events-{stamp}.sqlite3"
            archive = dest / f"events-{stamp}.sqlite3.gz"
            bundle = dest / f"events-{stamp}{SNAPSHOT_BUNDLE_SUFFIX}"
            for stale in (plain, archive, bundle):
                if stale.exists():
                    stale.unlink()

            self._conn.execute("VACUUM INTO ?", (str(plain),))
            try:
                with open(plain, "rb") as src, open(archive, "wb") as dst:
                    with gzip.GzipFile(fileobj=dst, mode="wb", mtime=0) as gz:
                        shutil.copyfileobj(src, gz)
            finally:
                plain.unlink(missing_ok=True)

            # The lock is held, and this process is the sole writer, so no new
            # sidecar can appear between the VACUUM and this bundle.
            _bundle_sidecars(self._snapshot_dir, bundle)

            return self.verify_backup(
                archive, expect_rows=self.count(), expect_head=self._head
            )

    def verify_backup(
        self,
        archive_path: str | os.PathLike[str],
        *,
        snapshots_archive: str | os.PathLike[str] | None = None,
        expect_rows: int | None = None,
        expect_head: ChainHead | None = None,
    ) -> dict:
        """Restore ``archive_path`` to a temp path and prove it end to end.

        Sidecars are restored from ``snapshots_archive`` (defaulting to the
        bundle that sits beside ``archive_path``) into the same temp area, and
        the probe reads *only* those. That is the whole point: a backup whose
        bundle is missing, damaged, or short of a referenced sidecar must fail
        here, exactly as it would on a real off-box restore — the live snapshot
        directory is never consulted and so can never mask the gap.
        """
        archive_path = Path(archive_path)
        bundle = (
            Path(snapshots_archive)
            if snapshots_archive is not None
            else _sidecar_bundle_path(archive_path)
        )
        workdir = Path(tempfile.mkdtemp(prefix="tradebot-eventlog-verify-"))
        try:
            restored = workdir / "restored.sqlite3"
            try:
                with gzip.open(archive_path, "rb") as gz, open(restored, "wb") as out:
                    shutil.copyfileobj(gz, out)
            except _DECOMPRESS_ERRORS as exc:
                raise BackupVerificationError(
                    f"backup {archive_path} could not be decompressed: {exc}"
                ) from exc

            # A missing bundle is not an error by itself — a log that never
            # spilled a sidecar needs none. It becomes one below, as a plain
            # "snapshot sidecar missing" RECOVERY_REQUIRED, the moment the
            # restored chain actually references a sidecar.
            restored_snapshots = workdir / "snapshots"
            restored_snapshots.mkdir(parents=True, exist_ok=True)
            sidecars = 0
            if bundle.exists():
                try:
                    sidecars = _unbundle_sidecars(bundle, restored_snapshots)
                except _BUNDLE_ERRORS as exc:
                    raise BackupVerificationError(
                        f"backup sidecar bundle {bundle} could not be read: {exc}"
                    ) from exc

            try:
                probe = EventLog(
                    restored,
                    self._clock,
                    snapshot_dir=restored_snapshots,
                    busy_timeout_ms=self._busy_timeout_ms,
                )
            except sqlite3.DatabaseError as exc:
                raise BackupVerificationError(
                    f"backup {archive_path} did not open as a database: {exc}"
                ) from exc

            try:
                head = probe.verify_chain()
                rows = probe.count()
            except RecoveryRequired as exc:
                raise BackupVerificationError(
                    f"backup {archive_path} failed chain verification: {exc}"
                ) from exc
            except sqlite3.DatabaseError as exc:
                raise BackupVerificationError(
                    f"backup {archive_path} is not a readable event log: {exc}"
                ) from exc
            finally:
                probe.close()

            if expect_rows is not None and rows != expect_rows:
                raise BackupVerificationError(
                    f"backup {archive_path} holds {rows} rows, source has {expect_rows}"
                )
            if expect_head is not None and head != expect_head:
                raise BackupVerificationError(
                    f"backup {archive_path} head {head} does not match source {expect_head}"
                )

            return {
                "archive": str(archive_path),
                "snapshots_archive": str(bundle) if bundle.exists() else None,
                "rows": rows,
                "sidecars": sidecars,
                "chain_head": head,
                "verified": True,
            }
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_envelope(row: sqlite3.Row) -> Envelope:
    return envelope_from_dict(
        {
            "event_id": row["event_id"],
            "schema": row["schema"],
            "schema_version": row["schema_version"],
            "ts_event": row["ts_event"],
            "ts_ingest": row["ts_ingest"],
            "correlation_id": row["correlation_id"],
            "parent_ids": json.loads(row["parent_ids"]),
            "idempotency_key": row["idempotency_key"],
            "actor": row["actor"],
            "payload": json.loads(row["payload"]),
            "seq": row["seq"],
        }
    )


def _relative_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _sidecar_bundle_path(archive_path: Path) -> Path:
    """The ``…snapshots.tar.gz`` that belongs to a ``…sqlite3.gz`` backup."""
    name = archive_path.name
    for suffix in (".sqlite3.gz", ".sqlite3", ".gz"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return archive_path.with_name(name + SNAPSHOT_BUNDLE_SUFFIX)


def _bundle_sidecars(snapshot_dir: Path, bundle: Path) -> int:
    """Tar every snapshot sidecar into ``bundle``, flat, by basename.

    Flat because :meth:`EventLog._verify_sidecar` resolves sidecars by
    basename; the bundle therefore restores into any directory. Returns the
    number of files bundled (0, and no file written, if there are none).
    """
    if not snapshot_dir.is_dir():
        return 0
    files = sorted(p for p in snapshot_dir.iterdir() if p.is_file())
    if not files:
        return 0
    bundle.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the gzip header timestamp out; sorted order keeps member
    # order stable. (Per-member tar mtimes still come from the files.)
    with open(bundle, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for path in files:
                    tar.add(path, arcname=path.name)
    return len(files)


def _unbundle_sidecars(bundle: Path, dest_dir: Path) -> int:
    """Extract a sidecar bundle into ``dest_dir``, flat and by basename.

    Members are read and rewritten by hand rather than via ``extractall`` so a
    crafted bundle cannot write outside ``dest_dir`` (no absolute paths, no
    ``..``, no symlinks/devices — regular files only).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with tarfile.open(bundle, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if not name or name in (".", ".."):
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, open(dest_dir / name, "wb") as out:
                shutil.copyfileobj(source, out)
            extracted += 1
    return extracted


def _month_key(ts_event_ns: int) -> str:
    return datetime.fromtimestamp(ts_event_ns // 1_000_000_000, timezone.utc).strftime("%Y%m")


def _write_parquet(path: Path, rows: list, *, archived_at_ns: int, source_db: str) -> int:
    """Write/extend ``events-YYYYMM.parquet``, chain columns and metadata intact.

    Returns the number of rows actually written, so a caller can tell a real
    archive from a no-op — ``len(rows)`` offered is not the same number.

    Parquet cannot be appended to, so an existing month file is read back and
    rewritten with the new rows concatenated.

    Idempotent under retry, because :meth:`EventLog.archive_before` cannot make
    the Parquet write and the SQLite delete one transaction: a crash between
    the two leaves the rows both archived *and* still live, and the next run
    re-offers exactly the same rows. A row whose ``seq`` is already in the file
    is therefore dropped rather than concatenated (Parquet has no unique
    constraint to lean on) — but ONLY when its ``row_hash`` matches the stored
    one. A colliding ``seq`` carrying a *different* ``row_hash`` is not a retry:
    it means the live chain and this archive disagree about what happened at
    that point in history, which is exactly the "not provably intact" condition
    this module exists to announce, so it raises :class:`RecoveryRequired`.
    Dropping it instead would delete live rows that were never archived (the
    caller's DELETE runs regardless) — silent, unrecoverable loss.

    The result lands via a temp file + atomic rename so a crash mid-write can
    never leave a half-written month file that the retry would fail to read.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError("archiving the event log requires pyarrow") from exc

    schema = pa.schema(
        [
            pa.field("seq", pa.int64()),
            pa.field("event_id", pa.string()),
            pa.field("schema", pa.string()),
            pa.field("schema_version", pa.int32()),
            pa.field("ts_event", pa.int64()),
            pa.field("ts_ingest", pa.int64()),
            pa.field("correlation_id", pa.string()),
            pa.field("parent_ids", pa.string()),
            pa.field("idempotency_key", pa.string()),
            pa.field("actor", pa.string()),
            pa.field("payload", pa.string()),
            pa.field("prev_hash", pa.string()),
            pa.field("row_hash", pa.string()),
        ]
    )
    columns = {name: [row[name] for row in rows] for name in _EVENT_COLUMNS}
    table = pa.Table.from_pydict(columns, schema=schema)

    if path.exists():
        existing = pq.read_table(path).select(list(_EVENT_COLUMNS))
        existing = existing.cast(schema).replace_schema_metadata(None)
        already = dict(
            zip(
                existing.column("seq").to_pylist(),
                existing.column("row_hash").to_pylist(),
            )
        )
        if already:
            keep = []
            for seq, row_hash in zip(columns["seq"], columns["row_hash"]):
                stored = already.get(seq)
                if stored is None:
                    keep.append(True)
                elif stored == row_hash:
                    keep.append(False)  # genuine retry — already archived
                else:
                    raise RecoveryRequired(
                        f"{path.name} already holds a different event at seq {seq} "
                        f"(archived row_hash {stored}, live row_hash {row_hash}); "
                        "the live chain and this archive disagree — refusing to "
                        "archive, because deleting these rows would lose them"
                    )
            table = table.filter(pa.array(keep, type=pa.bool_()))
        table = pa.concat_tables([existing, table.replace_schema_metadata(None)])
        # A retry re-offers rows in the same order, but sorting makes the file
        # deterministic no matter which run wrote which rows.
        table = table.sort_by([("seq", "ascending")])
        written = table.num_rows - existing.num_rows
    else:
        written = table.num_rows

    seqs = table.column("seq").to_pylist()
    if not seqs:
        # Nothing offered and nothing stored: no file to write, nothing written.
        return 0
    first_index = seqs.index(min(seqs))
    last_index = seqs.index(max(seqs))
    table = table.replace_schema_metadata(
        {
            "chain_first_seq": str(min(seqs)),
            "chain_last_seq": str(max(seqs)),
            "chain_first_prev_hash": table.column("prev_hash").to_pylist()[first_index],
            "chain_last_row_hash": table.column("row_hash").to_pylist()[last_index],
            "archived_at_ns": str(archived_at_ns),
            "source_db": source_db,
        }
    )
    scratch = path.with_name(path.name + ".partial")
    try:
        pq.write_table(table, scratch)
        os.replace(scratch, path)
    finally:
        if scratch.exists():
            scratch.unlink()
    return written
