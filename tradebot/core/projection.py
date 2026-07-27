"""tradebot.core.projection — ``fold(events) -> state`` (M0-4).

Implements the ``project(snap); apply tail events in seq order`` step of the
boot pseudocode in docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md
§1.3. ``core/recovery.py`` drives it; this module is the pure half.

**Pure by construction.** No I/O, no ``sqlite3``, no import of
:mod:`tradebot.core.event_log`. A fold is a function of the envelopes handed to
it and nothing else, so it is testable without a database and identical for the
same stream on any machine.

**Schema-agnostic.** No concrete event family is wired in here. The
``market.*``/``order.*``/``position.*``/``breaker.*`` payload schemas of
pass3-systems.md §1.2 are design-doc only — none is registered via
``events.register`` yet — so this module ships the *registry* and the fold, and
the families register their own reducers as they land. Registration is by
``schema`` alone, not ``(schema, version)``: envelopes are upcast to the
schema's current version on the way out of the log
(:func:`tradebot.core.events.envelope_from_dict`), so a reducer only ever sees
current-version payloads.

Two rules the fold enforces, both deliberate:

* An envelope whose ``schema`` has no registered reducer is **skipped, never an
  error** — the "any (state, event) pair not listed is logged-and-ignored"
  convention of pass3-systems.md §2, applied to projection.
* ``snapshot.projection`` rows are **skipped too**. A snapshot is a derived
  artefact of prior folding, not a source fact; re-folding one would double-count
  the history it summarises. (``recovery.py`` uses a snapshot the other way
  round — as the *initial state* the tail is folded onto.)

The only bookkeeping field the fold owns is ``state["last_seq"]``. It is
emphatically **not** ``row_hash``/``chain_head``: an
:class:`~tradebot.core.events.Envelope` carries no ``row_hash`` (see
``tradebot/core/events.py``, §1.1 minus the two writer-computed fields), so the
fold cannot reconstruct the chain hash and must not pretend to.
``EventLog.head()``/``EventLog.verify_chain()`` remain the sole source of the
hashed chain head.
"""

from __future__ import annotations

import logging
from collections import Counter
from contextlib import contextmanager
from typing import Callable, Iterable, Iterator, Optional

from tradebot.core.events import Envelope

logger = logging.getLogger(__name__)

#: Duplicated from ``event_log.SNAPSHOT_SCHEMA`` rather than imported, because
#: importing it would drag ``sqlite3`` and the whole log into this pure module.
#: ``tests/unit/test_tradebot_projection.py`` asserts the two stay equal.
SNAPSHOT_SCHEMA = "snapshot.projection"

#: The one key :func:`fold` writes itself.
LAST_SEQ = "last_seq"

#: ``reducer(state, envelope)`` returns the new state, or ``None`` if it
#: mutated ``state`` in place.
Reducer = Callable[[dict, Envelope], Optional[dict]]

_REDUCERS: dict[str, Reducer] = {}


# ---------------------------------------------------------------------------
# Reducer registry (same decorator shape as events.register)
# ---------------------------------------------------------------------------


def register_reducer(schema: str) -> Callable[[Reducer], Reducer]:
    """Decorator registering the reducer for ``schema``.

    Re-registering the *same* function is a no-op (module re-import). Binding a
    *different* function to a schema that already has one raises: a silently
    overwritten reducer would change the projection of the whole history
    depending on import order.
    """

    def decorator(fn: Reducer) -> Reducer:
        existing = _REDUCERS.get(schema)
        if existing is not None and existing is not fn:
            raise ValueError(
                f"a reducer for {schema!r} is already registered "
                f"({existing!r}); refusing to replace it with {fn!r}"
            )
        _REDUCERS[schema] = fn
        return fn

    return decorator


def reducer_for(schema: str) -> Reducer | None:
    return _REDUCERS.get(schema)


def registered_schemas() -> tuple[str, ...]:
    return tuple(sorted(_REDUCERS))


@contextmanager
def reducer_scope() -> Iterator[dict[str, Reducer]]:
    """Save the registry on entry, restore it on exit.

    The registry is module-global, so a test that registers a synthetic schema
    would otherwise leak it into every later test in the same process. Yields
    the live registry.
    """
    saved = dict(_REDUCERS)
    try:
        yield _REDUCERS
    finally:
        _REDUCERS.clear()
        _REDUCERS.update(saved)


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------


def fold(events: Iterable[Envelope], state: dict | None = None) -> dict:
    """Apply every envelope's reducer to ``state``, in the order given.

    ``state`` defaults to a fresh ``{}``. A caller-supplied ``state`` is
    shallow-copied, so folding never mutates the dict it was handed (a snapshot
    payload, typically) — reducers that touch nested containers must copy them,
    as the reducers in this codebase's tests do.

    ``events`` must arrive in ascending ``seq`` order, which is what
    :meth:`tradebot.core.event_log.EventLog.read` guarantees.

    ``state[LAST_SEQ]`` is the replay watermark: the highest ``seq`` this fold
    *consumed*, including envelopes it skipped. Skipped rows still happened, so
    advancing past them is the point — a tail made entirely of not-yet-mapped
    schemas would otherwise leave the watermark stuck and the same events would
    be re-offered on every resume. Envelopes with ``seq is None`` (never
    persisted) leave it alone.
    """
    result: dict = {} if state is None else dict(state)
    result.setdefault(LAST_SEQ, 0)

    ignored: Counter = Counter()
    for envelope in events:
        if envelope.schema == SNAPSHOT_SCHEMA:
            ignored[envelope.schema] += 1
        else:
            reducer = _REDUCERS.get(envelope.schema)
            if reducer is None:
                ignored[envelope.schema] += 1
            else:
                returned = reducer(result, envelope)
                if returned is not None:
                    result = returned

        seq = envelope.seq
        if seq is not None and seq > int(result.get(LAST_SEQ) or 0):
            result[LAST_SEQ] = seq

    if ignored:
        # Aggregated, not per-event: a replay folds millions of rows and a line
        # each would drown the log it is trying to explain.
        logger.debug(
            "projection.fold ignored %d event(s) with no reducer: %s",
            sum(ignored.values()),
            dict(ignored),
        )
    return result
