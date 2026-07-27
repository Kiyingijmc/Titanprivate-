"""tradebot.core.recovery — the verify-then-replay boot sequence (M0-4).

Implements the ``verify_and_replay()`` pseudocode of
docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md §1.3, and the boot
half of §1.4/F-015 ("the core process is the sole writer to the events DB.
Total").

``event_log.py`` (M0-3) produces the integrity *signal* and says so in its own
docstring: the ``RECOVERY_REQUIRED`` operating mode belongs here. So this is
where a chain break stops being an exception and becomes a boot decision:

* chain verifies → :data:`OK`, with the projected ``state`` and the verified
  :class:`~tradebot.core.event_log.ChainHead`;
* chain does not → :data:`RECOVERY_REQUIRED`, with **no state at all**. Not a
  partial projection, not a best-effort one. "Best-effort replay and go is a
  forbidden code path" (pass3-systems.md:123), and the cheapest way to keep it
  forbidden is to make the successful path the only one that can hand back a
  state object.

Sole writer, at boot (F-015)
----------------------------
:func:`acquire_boot_lock` takes an exclusive, non-blocking ``flock`` on a
``<db_path>.boot.lock`` sidecar before any usable boot result is returned, so a
second core process against the same log fails *immediately* rather than
racing. This is strictly stronger than the ``busy_timeout`` contention path
``EventLog`` already has: that one makes two writers interleave *safely*
(``tests/unit/test_tradebot_event_log.py``'s ``TestSoleWriter``), which is a
correctness backstop, not a refusal. The lock lives here and only here —
``EventLog``'s construction contract is deliberately untouched, so its internal
second-instance probe in ``verify_backup`` keeps working.

POSIX ``fcntl.flock`` is used directly: the Python side of this project runs on
WSL/Linux (CLAUDE.md), and Windows portability is explicitly out of scope.

Scope simplifications (deliberate, M0-4)
----------------------------------------
The §1.3 pseudocode has two further boot steps that are **not** implemented
here, because the subsystems they call do not exist under ``tradebot/`` yet and
inventing their APIs now would mean writing them twice:

* the feature restart policy (§4.5 / F-014) — there is no ``tradebot/features/``;
* the ``STARTUP`` broker-truth reconcile (§3.3) — there is no broker adapter.

Neither is stubbed. When those packages land, they hook in between the fold and
the returned :class:`BootResult`, and the ``QUARANTINE``/``REFUSE_TRADE``
verdicts join ``INTEGRITY_FAIL`` in gating trading. The human-ack workflow that
lifts ``RECOVERY_REQUIRED`` (GUI/Telegram) is likewise a later session's; all
this module owes it is a correct refusal.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import logging
import os
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from tradebot.core import projection
from tradebot.core.event_log import (
    RECOVERY_REQUIRED,
    ChainHead,
    EventLog,
    RecoveryRequired,
)

logger = logging.getLogger(__name__)

#: The status of a boot that may trade.
OK = "OK"

#: Suffix of the boot lock that sits beside the events DB.
BOOT_LOCK_SUFFIX = ".boot.lock"

# gzip/zlib surface sidecar damage through these three; EOFError is not an
# OSError, so it has to be named explicitly (same set as event_log.py).
_DECOMPRESS_ERRORS = (OSError, EOFError, zlib.error)


class BootLockUnavailable(RuntimeError):
    """Another process already holds this log's boot lock.

    Distinct from :class:`~tradebot.core.event_log.RecoveryRequired`: the log
    may be perfectly intact. What is wrong is that someone else owns it, and
    F-015 allows exactly one owner.
    """


# ---------------------------------------------------------------------------
# Boot lock (F-015)
# ---------------------------------------------------------------------------


class BootLock:
    """An exclusive ``flock`` held on ``<db_path>.boot.lock``."""

    def __init__(self, path: Path, fd: int) -> None:
        self.path = path
        self._fd: int | None = fd

    @property
    def held(self) -> bool:
        return self._fd is not None

    def release(self) -> None:
        """Drop the lock. Idempotent, so it is safe in ``addCleanup``/``finally``."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "BootLock":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"BootLock(path={str(self.path)!r}, held={self.held})"


def boot_lock_path(db_path: str | os.PathLike[str]) -> Path:
    return Path(str(db_path) + BOOT_LOCK_SUFFIX)


def acquire_boot_lock(db_path: str | os.PathLike[str]) -> BootLock:
    """Take the exclusive boot lock for ``db_path``, or fail at once.

    ``LOCK_NB`` is the whole point: a second core process must be told "no"
    now, not after a timeout that looks like a slow disk. The lock file is left
    on disk after release — unlinking it would race a second process that has
    already opened it.

    Raises :class:`BootLockUnavailable` if it is held elsewhere.
    """
    path = boot_lock_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise BootLockUnavailable(
            f"another process holds the boot lock {path}: {exc}"
        ) from exc
    except BaseException:
        os.close(fd)
        raise

    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError:  # pragma: no cover - the pid is a diagnostic, not the lock
        logger.warning("could not record the owning pid in %s", path)
    return BootLock(path, fd)


# ---------------------------------------------------------------------------
# Boot result
# ---------------------------------------------------------------------------


@dataclass
class BootResult:
    """What the boot sequence decided.

    ``state`` is a dict on :data:`OK` and ``None`` on
    :data:`~tradebot.core.event_log.RECOVERY_REQUIRED` — there is no third,
    "partial" shape by design.

    The boot lock rides along on *both* outcomes and is the caller's to
    :meth:`release`. It is deliberately still held under
    ``RECOVERY_REQUIRED``: that mode keeps managing exits on the existing
    positions, so this process remains the log's sole owner and a second one
    must still be refused.
    """

    status: str
    state: dict | None = None
    chain_head: ChainHead | None = None
    reason: str | None = None
    snapshot_seq: int | None = None
    events_applied: int = 0
    lock: BootLock | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.status == OK

    @property
    def recovery_required(self) -> bool:
        return self.status == RECOVERY_REQUIRED

    def release(self) -> None:
        if self.lock is not None:
            self.lock.release()

    def __enter__(self) -> "BootResult":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


# ---------------------------------------------------------------------------
# The boot sequence
# ---------------------------------------------------------------------------


def verify_and_replay(event_log: EventLog, *, lock: bool = True) -> BootResult:
    """Verify the chain, then project the newest snapshot plus its tail.

    Order matters: the boot lock is taken *first*, so nothing can append while
    the chain is being walked; then :meth:`EventLog.verify_chain` runs; only a
    chain that verified end to end is folded.

    ``lock=False`` skips the boot lock. It exists for read-only callers
    (offline analysis of a copied log) — the core process must never use it.

    Raises :class:`BootLockUnavailable` if another process owns the log.
    Returns — never raises — :data:`RECOVERY_REQUIRED` for every integrity
    break, so the caller has to look at ``status`` to get at a state.
    """
    boot_lock = acquire_boot_lock(event_log.db_path) if lock else None
    try:
        head = event_log.verify_chain()
        snapshot_seq, initial = _initial_state(event_log)
        tail = event_log.read(from_seq=0 if snapshot_seq is None else snapshot_seq + 1)
        state = projection.fold(tail, initial)
    except RecoveryRequired as exc:
        logger.error("boot refused: %s", exc)
        return BootResult(
            status=RECOVERY_REQUIRED,
            state=None,
            chain_head=None,
            reason=str(exc),
            lock=boot_lock,
        )
    except BaseException:
        # Anything that is not an integrity verdict (a programming error, an
        # unreadable file) must not leave the lock stranded.
        if boot_lock is not None:
            boot_lock.release()
        raise

    return BootResult(
        status=OK,
        state=state,
        chain_head=head,
        snapshot_seq=snapshot_seq,
        events_applied=len(tail),
        lock=boot_lock,
    )


def _initial_state(event_log: EventLog) -> tuple[int | None, dict]:
    """``(snapshot_seq, state)`` for the newest retained snapshot, or ``(None, {})``."""
    seqs = event_log.snapshot_seqs()
    if not seqs:
        return None, {}

    seq = seqs[-1]
    rows = event_log.read(from_seq=seq, to_seq=seq)
    if not rows:
        # The chain verified a moment ago, so this cannot happen without
        # something writing underneath us — which is exactly what the boot lock
        # exists to prevent, and exactly the kind of surprise that must not be
        # replayed through.
        raise RecoveryRequired("the newest snapshot row vanished during replay", seq=seq)

    state = dict(_snapshot_state(rows[0].payload, event_log, seq))
    # The snapshot summarises history *through* its own seq, so the watermark
    # starts there and the tail resumes at seq+1.
    state[projection.LAST_SEQ] = max(int(state.get(projection.LAST_SEQ) or 0), seq)
    return seq, state


def _snapshot_state(body: dict, event_log: EventLog, seq: int) -> dict:
    """The projection state a ``snapshot.projection`` event carries.

    Inline for small payloads; otherwise from the gzip sidecar the event names.
    ``verify_chain`` already proved that sidecar's SHA-256, but it resolves it
    by basename inside the log's snapshot directory while this resolves the
    recorded relative path against the DB directory. Re-checking the hash here
    costs one read and closes the gap between the two resolutions.
    """
    if not isinstance(body, dict):
        raise RecoveryRequired("snapshot payload is not an object", seq=seq)

    if "state" in body:
        state = body["state"]
        if not isinstance(state, dict):
            raise RecoveryRequired("inline snapshot state is not an object", seq=seq)
        return state

    sidecar = body.get("sidecar")
    if not sidecar:
        # A snapshot with neither inline state nor a sidecar is an empty
        # projection, which is what an empty log snapshots to.
        return {}

    path = event_log.db_path.parent / str(sidecar.get("path", ""))
    try:
        with gzip.open(path, "rb") as handle:
            raw = handle.read()
    except _DECOMPRESS_ERRORS as exc:
        raise RecoveryRequired(f"snapshot sidecar unreadable: {exc}", seq=seq) from exc

    if hashlib.sha256(raw).hexdigest() != sidecar.get("sha256"):
        raise RecoveryRequired("snapshot sidecar sha256 mismatch", seq=seq)

    try:
        state = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RecoveryRequired(f"undecodable snapshot sidecar: {exc}", seq=seq) from exc
    if not isinstance(state, dict):
        raise RecoveryRequired("snapshot sidecar state is not an object", seq=seq)
    return state
