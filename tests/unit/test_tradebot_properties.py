"""Property-based invariants P4-P8 + P11 groundwork (M0-6).

The named invariant table is
docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md §7.2; P11 is
pass6-accounting.md §6.3 (the rounding law of pass6-accounting.md:58). This
module is the property tier of the PR checks (pass3 §8.6), run by
scripts/run_pr_checks.sh — there is no hosted CI while the repo has no remote.

Live here today
---------------
=====  ==========================================================  ===========
 ID    Invariant                                                   Subject
=====  ==========================================================  ===========
 P4    any mutation/deletion/truncation of the chained log is       core/
       detected, never a clean verify                              event_log.py
 P5    no transition out of a terminal state; a losing request      core/sta.py
       resolves, never raises
 P6    replaying a log twice -- or one with writer-side duplicate   core/
       drops -- yields identical projections                       projection.py
 P7    equivalent params collide, distinct params never do          core/events.py
       (F-038)                                                     canonical_json
 P8    normalize_price results always land on the tick grid         src/risk/
                                                                   risk_manager.py
 P11   a posting balances exactly after half-even rounding to       (groundwork:
       micro-units, residual absorbed by the largest line          reference law)
=====  ==========================================================  ===========

Deferred (their subjects do not exist yet): P1/P2/P3/P9/P10 -- feature nodes,
sizing, the ledger, BarClock and reconcile land in M1/M2.

P8 targets ``src/risk/risk_manager.py`` rather than anything under
``tradebot/``: that is the implementation pass3 §6.1 marks **ADAPT** into
``tradebot/risk/sizing.py`` at M2, and pinning the invariant now is what stops
the copy from arriving pre-broken. This is a test importing ``src/``; no
module under ``tradebot/`` does (the M0 fence holds).

P11 is groundwork, not the money engine. pass8-synthesis.md §4.2 fences the
double-entry ledger into M2, so the rounding law lives here as an executable
reference (:func:`round_posting`) whose properties are fuzzed now; M2 replaces
the reference with an import of the real ``tradebot/money/`` implementation and
keeps the assertions.

Why this module does not import ``hypothesis``
----------------------------------------------
The dependency itself is decided: the approved S007 spec (2026-07-27) pins
``hypothesis>=6,<7`` in ``requirements.txt`` and as the ``[test]`` extra in
``pyproject.toml`` -- the authoritative record is ``docs/TRADEBOT_CI.md`` §3.
These tests nonetheless run on seeded ``random.Random`` + ``subTest``:
(a) fixed seeds make a failure reproducible by seed alone, with no
``.hypothesis`` example database to ship or ignore; (b) hypothesis's
database/deadline machinery introduces run-to-run variability that the mig
verify gate reads as flake, and P4-P8's small, well-understood input spaces
don't yet earn that variance. The cost is real and named: no shrinking, so a
counter-example arrives at full size, and coverage is only as good as the
generators below. ``@given`` adoption lands at M1, where P1
(incremental == batch across every feature node) is the invariant that
genuinely wants shrinking -- starting from the already-pinned version.

NOTE ON LOCATION: flat under tests/unit/ like every other module here. A test
package named ``tradebot`` would shadow the real top-level package during
``unittest discover -s tests/unit`` (see test_tradebot_event_log.py's note).
"""

import asyncio
import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.risk.risk_manager import RiskManager  # noqa: E402
from tradebot.core.bus import EventBus  # noqa: E402
from tradebot.core.clock import SimClock  # noqa: E402
from tradebot.core.event_log import EventLog, RecoveryRequired  # noqa: E402
from tradebot.core.events import Envelope, canonical_json  # noqa: E402
from tradebot.core.projection import fold, register_reducer, reducer_scope  # noqa: E402
from tradebot.core.sta import SignalTransitionActor  # noqa: E402

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

#: Base seed. Every case derives its own seed from this plus its index, so a
#: failing subTest reports a seed that reproduces it in isolation.
SEED = 20260728

#: Cases per property. Sized so the whole module stays well under the unit
#: tier's minute budget; the nightly tier is where volume belongs (pass3 §8.6).
CASES = 40

#: P4 builds a fresh SQLite log per case, so it gets a smaller budget.
CHAIN_CASES = 24

BASE_TS = int(datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc).timestamp()) * 1_000_000_000

_HEX = "0123456789abcdef"
_TEXT = "abcdefghijklmnopqrstuvwxyz0123456789"


def case_rng(index: int) -> random.Random:
    """A generator seeded per case: reproduce a failure with this seed alone."""
    return random.Random(SEED + index)


def _flip(rng: random.Random, text: str, alphabet: str) -> str:
    """Replace one character of ``text`` with a *different* one."""
    position = rng.randrange(len(text))
    current = text[position]
    replacement = rng.choice([c for c in alphabet if c != current])
    return text[:position] + replacement + text[position + 1:]


# ---------------------------------------------------------------------------
# P4 -- hash chain (pass3 §7.2 P4, F-004)
# ---------------------------------------------------------------------------


class TestP4HashChainDetectsAnyMutation(unittest.TestCase):
    """Generated logs, randomised damage: ``verify_chain`` must always refuse.

    The example-based drills in test_tradebot_event_log.py pin five specific
    corruptions at fixed positions. This is the quantified version: for a
    random log length, a random damaged row, and a random kind of damage, the
    log is never allowed to verify clean.
    """

    #: Only the columns inside the pass3 §1.1 pre-image
    #: ``SHA-256(prev_hash | seq | schema | schema_version | ts_event | actor |
    #: canonical_json(payload))`` plus the structural damage kinds. See
    #: :class:`TestP4PreImageBoundary` for the columns deliberately outside it.
    KINDS = (
        "payload_char",
        "row_hash_char",
        "prev_hash_char",
        "ts_event",
        "schema_version",
        "schema",
        "actor",
        "delete_row",
        "truncate_tail",
    )

    def _build(self, tmp: Path, clock: SimClock, count: int) -> EventLog:
        log = EventLog(tmp / "events.sqlite3", clock)
        self.addCleanup(log.close)
        for i in range(count):
            log.append(
                "market.candle_closed",
                1,
                BASE_TS + i * 1_000_000_000,
                "core",
                {"instrument": "EURUSD", "bar_index": i, "close": 1.10000 + i},
            )
        return log

    def test_every_generated_mutation_forces_recovery_required(self):
        for index in range(CHAIN_CASES):
            rng = case_rng(index)
            count = rng.randint(2, 9)
            kind = self.KINDS[index % len(self.KINDS)]
            target = rng.randint(1, count)

            with self.subTest(seed=SEED + index, kind=kind, count=count, target=target):
                with tempfile.TemporaryDirectory() as name:
                    tmp = Path(name)
                    log = self._build(tmp, SimClock(BASE_TS), count)

                    # The log must verify clean *before* the damage, or the
                    # assertion below would prove nothing.
                    self.assertEqual(log.verify_chain().seq, count)

                    raw = sqlite3.connect(str(tmp / "events.sqlite3"), isolation_level=None)
                    raw.row_factory = sqlite3.Row
                    try:
                        self._damage(raw, rng, kind, target, count)
                    finally:
                        raw.close()

                    with self.assertRaises(RecoveryRequired):
                        log.verify_chain()

                    log.close()

    def _damage(self, raw, rng, kind, target, count):
        if kind == "delete_row":
            raw.execute("DELETE FROM events WHERE seq=?", (target,))
        elif kind == "truncate_tail":
            # Cut somewhere strictly inside the log so rows actually go.
            cut = rng.randint(1, count - 1)
            raw.execute("DELETE FROM events WHERE seq>?", (cut,))
        elif kind == "payload_char":
            payload = raw.execute(
                "SELECT payload FROM events WHERE seq=?", (target,)
            ).fetchone()["payload"]
            raw.execute(
                "UPDATE events SET payload=? WHERE seq=?",
                (_flip(rng, payload, _TEXT), target),
            )
        elif kind in ("row_hash_char", "prev_hash_char"):
            column = "row_hash" if kind == "row_hash_char" else "prev_hash"
            current = raw.execute(
                f"SELECT {column} FROM events WHERE seq=?", (target,)
            ).fetchone()[column]
            raw.execute(
                f"UPDATE events SET {column}=? WHERE seq=?",
                (_flip(rng, current, _HEX), target),
            )
        elif kind == "ts_event":
            raw.execute(
                "UPDATE events SET ts_event=ts_event+? WHERE seq=?",
                (rng.randint(1, 10_000), target),
            )
        elif kind == "schema_version":
            raw.execute("UPDATE events SET schema_version=2 WHERE seq=?", (target,))
        elif kind == "schema":
            raw.execute(
                'UPDATE events SET "schema"=? WHERE seq=?', ("market.candle_reopened", target)
            )
        elif kind == "actor":
            # Reassign the event to a different principal. Rows are written by
            # "core"; any other value must break the chain (S009).
            raw.execute(
                "UPDATE events SET actor=? WHERE seq=?",
                (rng.choice(("risk", "exec", "human:tg:1337", "breaker")), target),
            )
        else:  # pragma: no cover - guards a typo in KINDS
            raise AssertionError(f"unhandled damage kind {kind!r}")


class TestP4PreImageBoundary(unittest.TestCase):
    """What the chain does *not* cover, asserted so it cannot drift silently.

    pass3-systems.md:30 (as amended 2026-07-28) defines ``row_hash`` over seven
    fields. The remaining envelope columns -- ``event_id``, ``ts_ingest``,
    ``correlation_id``, ``parent_ids``, ``idempotency_key`` -- are stored but
    unchained, so editing them in the database is undetectable by
    ``verify_chain``. That is the design as written, not a defect found here:
    all five are delivery/bookkeeping metadata rather than audit substance,
    and widening the pre-image further is a spec change owned by §1.1.

    ``actor`` used to sit in this list. It was moved into the pre-image in
    S009 because §8.5 event-logs the commanding actor and M2's command audit
    is built on that provenance -- see
    docs/decisions/0001-widen-row-hash-preimage-actor.md. Its detection is
    asserted by ``TestP4HashChainDetectsAnyMutation`` (the ``actor`` damage
    kind) and by ``test_rewritten_actor_is_refused``.
    """

    UNCHAINED = (
        "event_id",
        "ts_ingest",
        "correlation_id",
        "parent_ids",
        "idempotency_key",
    )

    def test_columns_outside_the_documented_pre_image_are_not_chained(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            log = EventLog(tmp / "events.sqlite3", SimClock(BASE_TS))
            self.addCleanup(log.close)
            log.append(
                "market.candle_closed", 1, BASE_TS, "core", {"bar_index": 0},
                correlation_id="corr-1", idempotency_key="key-1",
            )
            self.assertEqual(log.verify_chain().seq, 1)

            raw = sqlite3.connect(str(tmp / "events.sqlite3"), isolation_level=None)
            try:
                for column in self.UNCHAINED:
                    raw.execute(f"UPDATE events SET {column}=? WHERE seq=1", (f"tampered-{column}",))
            finally:
                raw.close()

            # Still clean: these columns are outside the §1.1 pre-image.
            self.assertEqual(log.verify_chain().seq, 1)
            log.close()


# ---------------------------------------------------------------------------
# P5 -- state machines (pass3 §7.2 P5, F-008)
# ---------------------------------------------------------------------------

TERMINAL_STATES = ("EXECUTED", "EXPIRED", "REJECTED", "CANCELLED")


class _Signal:
    """The smallest machine with the shape P5 is about: one terminal step."""

    def __init__(self) -> None:
        self.state = "PENDING"
        self.ignored = 0  # the sm.unexpected_event counter of pass3 §2 note

    def is_pending(self) -> bool:
        if self.state != "PENDING":
            self.ignored += 1
            return False
        return True

    def enter(self, terminal: str) -> None:
        assert terminal in TERMINAL_STATES
        self.state = terminal


def _transition_envelope(index: int, terminal: str) -> Envelope:
    return Envelope(
        schema="test.property_signal_transition",
        schema_version=1,
        ts_event=BASE_TS + index,
        ts_ingest=BASE_TS + index,
        actor="sta",
        payload={"index": index, "terminal": terminal},
    )


class TestP5NoTransitionOutOfTerminal(unittest.TestCase):
    """Fuzz interleaved transition requests: exactly one wins, none raise.

    Every request is submitted concurrently and every guard re-reads the state
    at *processing* time, so this is the race-storm shape of F-008 shrunk to
    the mechanism that exists today. The two halves of P5 asserted here: no
    transition leaves a terminal state (the winner's terminal state is final),
    and every unmatched (state, event) pair is *counted-ignored* rather than
    raised (``TransitionOutcome(accepted=False)``, ``ignored`` bumped).
    """

    def test_exactly_one_request_wins_every_interleaving(self):
        for index in range(CASES):
            rng = case_rng(index)
            count = rng.randint(2, 8)
            terminals = [rng.choice(TERMINAL_STATES) for _ in range(count)]
            # Number of event-loop yields each request takes inside its guard:
            # this is what varies the interleaving between cases.
            yields = [rng.randint(0, 3) for _ in range(count)]

            with self.subTest(seed=SEED + index, count=count, terminals=terminals):
                accepted, published, signal = asyncio.run(
                    self._race(count, terminals, yields)
                )

                self.assertEqual(len(accepted), 1, "more than one transition was accepted")
                self.assertEqual(len(published), 1, "the bus saw a second transition event")
                self.assertIn(signal.state, TERMINAL_STATES)
                self.assertEqual(signal.state, published[0].payload["terminal"])
                # Every loser resolved as a counted race_loser, not an exception.
                self.assertEqual(signal.ignored, count - 1)

    async def _race(self, count, terminals, yields):
        bus = EventBus()
        published = []
        bus.subscribe("test.property_signal_transition", published.append, name="probe")

        actor = SignalTransitionActor(bus)
        signal = _Signal()

        def make(i):
            async def guard():
                for _ in range(yields[i]):
                    await asyncio.sleep(0)
                return signal.is_pending()

            def apply():
                signal.enter(terminals[i])
                return _transition_envelope(i, terminals[i])

            return guard, apply

        tasks = []
        for i in range(count):
            guard, apply = make(i)
            tasks.append(asyncio.ensure_future(actor.submit(guard, apply)))

        outcomes = await asyncio.gather(*tasks)
        await actor.aclose()

        accepted = [o for o in outcomes if o.accepted]
        for outcome in outcomes:
            if not outcome.accepted:
                self.assertEqual(outcome.reason, "race_loser")
        return accepted, published, signal


# ---------------------------------------------------------------------------
# P6 -- projection idempotency (pass3 §7.2 P6)
# ---------------------------------------------------------------------------

P6_SCHEMAS = ("test.property_p6_alpha", "test.property_p6_beta", "test.property_p6_gamma")

#: A schema with no reducer: the fold must skip it and still advance last_seq.
P6_UNMAPPED = "test.property_p6_unmapped"


def _p6_reducer(state: dict, envelope: Envelope) -> dict:
    """Order-sensitive on purpose: a reducer that commutes proves less."""
    new = dict(state)
    counts = dict(new.get("counts", {}))
    counts[envelope.schema] = counts.get(envelope.schema, 0) + 1
    new["counts"] = counts
    new["total"] = new.get("total", 0) + int(envelope.payload["delta"])
    new["trail"] = list(new.get("trail", ())) + [envelope.payload["tag"]]
    return new


class TestP6ProjectionIdempotency(unittest.TestCase):
    def setUp(self):
        scope = reducer_scope()
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)
        for schema in P6_SCHEMAS:
            register_reducer(schema)(_p6_reducer)

    def _stream(self, rng, count):
        events = []
        for i in range(count):
            schema = rng.choice(P6_SCHEMAS + (P6_UNMAPPED,))
            events.append(
                Envelope(
                    schema=schema,
                    schema_version=1,
                    ts_event=BASE_TS + i,
                    ts_ingest=BASE_TS + i,
                    actor="core",
                    payload={"delta": rng.randint(-50, 50), "tag": f"t{i}"},
                    seq=i + 1,
                )
            )
        return events

    def test_folding_the_same_stream_twice_yields_identical_state(self):
        for index in range(CASES):
            rng = case_rng(index)
            events = self._stream(rng, rng.randint(1, 40))
            with self.subTest(seed=SEED + index, n=len(events)):
                self.assertEqual(fold(events), fold(events))

    def test_resuming_from_a_partial_fold_equals_folding_the_whole_stream(self):
        """The §1.3 boot shape: ``project(snap); apply tail`` == full replay."""
        for index in range(CASES):
            rng = case_rng(index)
            events = self._stream(rng, rng.randint(2, 40))
            split = rng.randrange(1, len(events))
            with self.subTest(seed=SEED + index, n=len(events), split=split):
                resumed = fold(events[split:], fold(events[:split]))
                self.assertEqual(resumed, fold(events))

    def test_writer_side_duplicate_drops_do_not_change_the_projection(self):
        """A stream with repeated idempotency keys folds to the de-duplicated one."""
        for index in range(CHAIN_CASES):
            rng = case_rng(index)
            count = rng.randint(4, 20)
            # A small key pool guarantees collisions; None means "no key".
            keys = [rng.choice([None, "k1", "k2", "k3"]) for _ in range(count)]
            payloads = [{"delta": rng.randint(-50, 50), "tag": f"t{i}"} for i in range(count)]
            schemas = [rng.choice(P6_SCHEMAS) for _ in range(count)]

            seen = set()
            unique = []
            for i in range(count):
                if keys[i] is not None:
                    if keys[i] in seen:
                        continue
                    seen.add(keys[i])
                unique.append(i)

            with self.subTest(seed=SEED + index, n=count, kept=len(unique)):
                with tempfile.TemporaryDirectory() as name:
                    tmp = Path(name)
                    with_dupes = self._fold_through_log(
                        tmp / "a.sqlite3", range(count), schemas, payloads, keys
                    )
                    deduped = self._fold_through_log(
                        tmp / "b.sqlite3", unique, schemas, payloads, keys
                    )
                self.assertEqual(with_dupes, deduped)
                self.assertEqual(with_dupes["last_seq"], len(unique))

    def _fold_through_log(self, db_path, indices, schemas, payloads, keys):
        log = EventLog(db_path, SimClock(BASE_TS))
        try:
            for i in indices:
                log.append(
                    schemas[i], 1, BASE_TS + i, "core", payloads[i], idempotency_key=keys[i]
                )
            return fold(log.read())
        finally:
            log.close()


# ---------------------------------------------------------------------------
# P7 -- params_hash collisions (pass3 §7.2 P7, F-038)
# ---------------------------------------------------------------------------


def _normal_form(value):
    """The equivalence classes ``canonical_json`` is *supposed* to collapse.

    Every branch is tagged, so ``True`` and ``1`` do not merge the way Python's
    own ``==``/``hash`` would (``True == 1``) -- a bug that would have made
    this oracle agree with a canonicaliser that emitted ``1`` for both.
    """
    if value is None:
        return ("null",)
    if value is True or value is False:
        return ("bool", value)
    if isinstance(value, float):
        if value == 0.0:  # covers -0.0
            return ("int", 0)
        if value.is_integer():
            return ("int", int(value))
        return ("float", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, (list, tuple)):
        return ("list", tuple(_normal_form(v) for v in value))
    if isinstance(value, dict):
        return ("dict", tuple(sorted((k, _normal_form(v)) for k, v in value.items())))
    raise AssertionError(f"generator produced an unmodelled type: {type(value)!r}")


class TestP7ParamsHash(unittest.TestCase):
    """``canonical_json`` is the substrate M1's ``params_hash`` will hash.

    So the collision property belongs to the canonicaliser: hashing cannot fix
    a canonical form that already lost the distinction.
    """

    # Floats are drawn across both formatting branches of ``_encode_float``:
    # the plain-``repr`` band and the sub-1e-4 band that falls back to an exact
    # ``Decimal`` expansion. The second band is where a truncating
    # implementation collapses distinct params onto one string.
    def _leaf(self, rng):
        kind = rng.choice(("int", "float", "tiny_float", "str", "bool", "none"))
        if kind == "int":
            return rng.randint(-1000, 1000)
        if kind == "float":
            return rng.choice([20.0, -0.0, 0.5, 1.25, 3.3333333333333335, 1e-4])
        if kind == "tiny_float":
            return rng.choice([1e-5, 2e-5, 1e-20, 2e-20, 1.5e-11, 3e-7])
        if kind == "str":
            return rng.choice(["20", "n", "", "EURUSD", "0"])
        if kind == "bool":
            return rng.choice([True, False])
        return None

    def _params(self, rng, depth=0):
        params = {}
        for _ in range(rng.randint(1, 5)):
            key = f"p{rng.randint(0, 6)}"
            if depth < 2 and rng.random() < 0.25:
                params[key] = self._params(rng, depth + 1)
            elif rng.random() < 0.2:
                params[key] = [self._leaf(rng) for _ in range(rng.randint(0, 3))]
            else:
                params[key] = self._leaf(rng)
        return params

    @staticmethod
    def _equivalent(rng, params):
        """A params dict that must hash identically: keys reordered, integral
        floats swapped for ints (and back), ``-0.0`` for ``0``."""
        items = list(params.items())
        rng.shuffle(items)
        out = {}
        for key, value in items:
            if isinstance(value, dict):
                out[key] = TestP7ParamsHash._equivalent(rng, value)
            elif value is True or value is False:
                out[key] = value  # never touch bools: True is not 1 here
            elif isinstance(value, int):
                out[key] = float(value) if rng.random() < 0.5 else value
            elif isinstance(value, float) and value.is_integer():
                # Also the -0.0 case: (-0.0).is_integer() is True and
                # int(-0.0) == 0, which is the collapse §4.2 requires.
                out[key] = int(value) if rng.random() < 0.5 else value
            else:
                out[key] = value
        return out

    def test_equivalent_params_always_collide(self):
        for index in range(CASES):
            rng = case_rng(index)
            params = self._params(rng)
            twin = self._equivalent(rng, params)
            with self.subTest(seed=SEED + index, params=params):
                self.assertEqual(_normal_form(params), _normal_form(twin), "generator bug")
                self.assertEqual(canonical_json(params), canonical_json(twin))

    def test_distinct_params_never_collide(self):
        """Across a whole generated corpus: one canonical string per class."""
        by_form = {}
        for index in range(CASES * 8):
            rng = case_rng(index)
            params = self._params(rng)
            form = _normal_form(params)
            encoded = canonical_json(params)
            if form in by_form:
                self.assertEqual(
                    by_form[form][1], encoded,
                    f"equivalent params encoded differently (seed {SEED + index})",
                )
            else:
                for other_form, (other_params, other_encoded) in by_form.items():
                    if other_encoded == encoded:
                        self.fail(
                            f"collision (seed {SEED + index}): {params!r} and "
                            f"{other_params!r} both encode to {encoded!r} but are "
                            f"distinct ({form!r} vs {other_form!r})"
                        )
                by_form[form] = (params, encoded)

        # The corpus has to actually exercise both, or the loop above proves
        # nothing about either half.
        self.assertGreater(len(by_form), 50, "corpus too small to be evidence")

    def test_sub_micro_floats_do_not_collapse_onto_one_string(self):
        """Regression guard for the truncating ``%.17f`` canonical form.

        A 17-decimal fixed-point fallback renders every float below ~1e-17 as
        ``"0.0"``, so ``{n: 1e-20}`` and ``{n: 2e-20}`` -- genuinely different
        strategy params -- would hash identically (F-038).
        """
        encodings = {canonical_json({"n": v}) for v in (1e-18, 1e-20, 2e-20, 1e-300, 5e-324)}
        self.assertEqual(len(encodings), 5)
        for encoded in encodings:
            self.assertNotIn("e", encoded.lower())

    def test_canonical_json_round_trips_through_json_loads(self):
        """Canonicalising must not change the value, only its spelling."""
        for index in range(CASES):
            rng = case_rng(index)
            params = self._params(rng)
            with self.subTest(seed=SEED + index):
                self.assertEqual(
                    canonical_json(json.loads(canonical_json(params))),
                    canonical_json(params),
                )


# ---------------------------------------------------------------------------
# P8 -- normalize_price lands on the tick grid (pass3 §7.2 P8)
# ---------------------------------------------------------------------------

#: (tick_size, low, high) -- realistic price bands per tick class, including
#: the two the invariant names explicitly (0.25 index ticks, 0.05) and the
#: 1e-05 five-digit forex tick that crashed the previous implementation.
TICK_BANDS = (
    (0.25, 100.0, 45000.0),      # US30 / index CFDs
    (0.05, 100.0, 20000.0),      # NAS100-class
    (0.01, 1.0, 4000.0),         # XAUUSD, oil
    (0.1, 100.0, 120000.0),      # BTCUSD-class
    (0.001, 0.5, 300.0),         # USDJPY 3-digit
    (0.0001, 0.5, 3.0),          # 4-digit forex
    (0.00001, 0.5, 3.0),         # 5-digit forex -- boot_crash.log case
    (1.0, 10.0, 50000.0),        # whole-unit tick
)


def _make_risk_manager():
    return RiskManager({"risk": {
        "account": {"max_daily_drawdown_pct": 3.0},
        "trade": {"risk_per_trade_pct": 1.0},
    }})


class TestP8NormalizePriceOnTickGrid(unittest.TestCase):
    """Whatever comes back is an exact integer multiple of the broker tick.

    Exactness is checked in ``Decimal``, not floats: the point of
    ``normalize_price`` is that its *result* is a clean price the broker will
    accept, and ``Decimal(str(result))`` is the value that actually goes on the
    wire. A float-tolerance check would pass on a result that still carries the
    ``1.20000000000001`` artefact the function exists to remove.
    """

    def test_results_are_exact_multiples_of_the_tick(self):
        for index in range(CASES * 4):
            rng = case_rng(index)
            tick, low, high = TICK_BANDS[index % len(TICK_BANDS)]
            price = rng.uniform(low, high)

            with self.subTest(seed=SEED + index, tick=tick, price=price):
                rm = _make_risk_manager()
                rm.update_symbol_specs("SYM", val=1.0, size=tick, v_min=0.01, v_step=0.01)
                result = rm.normalize_price(price, "SYM")

                self.assertGreater(result, 0.0)
                remainder = Decimal(str(result)) % Decimal(str(tick))
                self.assertEqual(
                    remainder, 0,
                    f"{result!r} is off the {tick} grid by {remainder}",
                )

    def test_snapping_never_moves_a_price_by_more_than_half_a_tick(self):
        """On-grid alone is satisfiable by returning 0; this pins *nearest*."""
        for index in range(CASES * 2):
            rng = case_rng(index)
            tick, low, high = TICK_BANDS[index % len(TICK_BANDS)]
            price = rng.uniform(low, high)

            with self.subTest(seed=SEED + index, tick=tick, price=price):
                rm = _make_risk_manager()
                rm.update_symbol_specs("SYM", val=1.0, size=tick, v_min=0.01, v_step=0.01)
                result = rm.normalize_price(price, "SYM")
                self.assertLessEqual(abs(result - price), tick / 2 + tick * 1e-6)

    def test_an_already_normal_price_is_a_fixed_point(self):
        """Normalising twice must not drift -- otherwise a modify loop walks."""
        for index in range(CASES * 2):
            rng = case_rng(index)
            tick, low, high = TICK_BANDS[index % len(TICK_BANDS)]
            price = rng.uniform(low, high)

            with self.subTest(seed=SEED + index, tick=tick, price=price):
                rm = _make_risk_manager()
                rm.update_symbol_specs("SYM", val=1.0, size=tick, v_min=0.01, v_step=0.01)
                once = rm.normalize_price(price, "SYM")
                self.assertEqual(rm.normalize_price(once, "SYM"), once)


# ---------------------------------------------------------------------------
# P11 groundwork -- posting balance + rounding law
# (pass6-accounting.md:58, §6.3)
# ---------------------------------------------------------------------------


def round_posting(amounts):
    """The pass6-accounting.md:58 rounding law, as executable reference.

    "Within a posting, each line rounds half-even to 1 micro-unit; the
    posting-level residual (<= n_lines micro-units) is added to the largest
    line so the posting balances *exactly*."

    ``amounts`` are exact ``Decimal`` line amounts denominated in micro-units
    (fractional values allowed -- that is what marks and conversions produce),
    and must sum to exactly zero, which is what "a posting" means. Returns a
    list of ``int`` micro-units summing to exactly zero.

    GROUNDWORK, not the money engine: the double-entry ledger is fenced into M2
    (pass8-synthesis.md §4.2). When ``tradebot/money/`` lands, delete this
    function, import the real one, and keep every assertion below.
    """
    if sum(amounts) != 0:
        raise ValueError("a posting's exact line amounts must sum to zero")

    rounded = [int(a.quantize(Decimal(1), rounding=ROUND_HALF_EVEN)) for a in amounts]
    residual = sum(rounded)
    if residual:
        # "the largest line": largest magnitude, ties broken by lowest index so
        # the law is deterministic rather than dict/sort-order dependent.
        absorber = min(range(len(amounts)), key=lambda i: (-abs(amounts[i]), i))
        rounded[absorber] -= residual
    return rounded


class TestP11PostingBalance(unittest.TestCase):
    def _posting(self, rng):
        """n exact line amounts summing to exactly zero.

        Amounts are quarter micro-units, so exact-half boundaries (the only
        place half-even differs from half-up) show up constantly. Quarters
        also keep every intermediate sum inside ``Decimal``'s 28-digit default
        context, which matters: with a divisor like 3 the balancing line would
        be a *rounded* remainder and ``sum(lines)`` would stop being exactly
        zero once the list is shuffled, breaking the premise rather than the
        law under test.
        """
        n = rng.randint(2, 8)
        lines = [Decimal(rng.randint(-20_000_000, 20_000_000)) / 4 for _ in range(n - 1)]
        lines.append(-sum(lines))
        rng.shuffle(lines)
        assert sum(lines) == 0, "generator lost exactness"
        return lines

    def test_every_posting_balances_exactly_after_rounding(self):
        for index in range(CASES * 3):
            rng = case_rng(index)
            lines = self._posting(rng)
            with self.subTest(seed=SEED + index, n=len(lines)):
                result = round_posting(lines)
                self.assertTrue(all(isinstance(x, int) for x in result))
                self.assertEqual(sum(result), 0, "posting does not balance")

    def test_residual_is_bounded_and_absorbed_by_exactly_one_line(self):
        naive_ever_unbalanced = False
        for index in range(CASES * 3):
            rng = case_rng(index)
            lines = self._posting(rng)
            naive = [int(a.quantize(Decimal(1), rounding=ROUND_HALF_EVEN)) for a in lines]
            residual = sum(naive)
            naive_ever_unbalanced |= residual != 0

            with self.subTest(seed=SEED + index, residual=residual):
                self.assertLessEqual(abs(residual), len(lines), "residual exceeds n_lines")

                result = round_posting(lines)
                differing = [
                    i for i, (adjusted, plain) in enumerate(zip(result, naive))
                    if adjusted != plain
                ]
                self.assertLessEqual(len(differing), 1)
                if differing:
                    absorber = differing[0]
                    self.assertEqual(result[absorber] - naive[absorber], -residual)
                    # It really is the largest line by magnitude.
                    self.assertEqual(
                        abs(lines[absorber]), max(abs(x) for x in lines)
                    )

        # Teeth: if naive rounding always balanced, the residual rule would be
        # dead code and every assertion above would be vacuous.
        self.assertTrue(
            naive_ever_unbalanced,
            "no generated posting needed residual absorption -- the fuzz is too tame",
        )

    def test_rounding_is_half_even_not_half_up(self):
        """Half-up would bias every .5 boundary away from zero, and a ledger
        that biases is a ledger that drifts."""
        self.assertEqual(round_posting([Decimal("0.5"), Decimal("-0.5")]), [0, 0])
        self.assertEqual(round_posting([Decimal("1.5"), Decimal("-1.5")]), [2, -2])
        self.assertEqual(round_posting([Decimal("2.5"), Decimal("-2.5")]), [2, -2])

    def test_the_law_does_not_mutate_its_input(self):
        """Re-rounding the same sequence yields the same answer.

        NB this is a *non-mutation* check and nothing more: `list(lines)` is a
        shallow copy in the same order, so it holds for any pure function of the
        input. The determinism that actually matters -- which line absorbs the
        residual when two are tied for largest -- is pinned by the test below.
        """
        for index in range(CASES):
            rng = case_rng(index)
            lines = self._posting(rng)
            with self.subTest(seed=SEED + index):
                self.assertEqual(round_posting(lines), round_posting(list(lines)))

    def test_ties_for_largest_line_break_to_the_lowest_index(self):
        """The residual lands on a *position*, not on whichever tied line the
        iteration happened to reach first.

        `round_posting`'s own comment claims "ties broken by lowest index so the
        law is deterministic rather than dict/sort-order dependent" -- but no
        assertion held it to that. Swap the tie-break to the highest index and
        every other test in this class still passes, while M2 would inherit a
        ledger whose residual lands somewhere else.

        Both postings below have their largest magnitude (4.4) tied across
        indices 0 and 1 and need a -1 residual absorbed, so the absorber is
        observable in the output: it is the only line that moves off its own
        half-even rounding.
        """
        lines = [Decimal("4.4"), Decimal("-4.4"), Decimal("0.5"), Decimal("0.5"), Decimal("-1")]
        # 4.4 -> 4 half-even; index 0 absorbs the -1 residual, so 4 -> 5.
        self.assertEqual(round_posting(lines), [5, -4, 0, 0, -1])

        # Same tie, opposite signs on the tied pair. Index 0 still absorbs
        # (-4 -> -3), proving the choice follows index, not sign or magnitude
        # ordering. A highest-index tie-break would move it to index 1 here.
        mirrored = [Decimal("-4.4"), Decimal("4.4"), Decimal("0.5"), Decimal("0.5"), Decimal("-1")]
        self.assertEqual(round_posting(mirrored), [-3, 4, 0, 0, -1])

        for result in (round_posting(lines), round_posting(mirrored)):
            self.assertEqual(sum(result), 0, "a posting must still balance exactly")

    def test_a_posting_that_does_not_sum_to_zero_is_refused(self):
        with self.assertRaises(ValueError):
            round_posting([Decimal(1), Decimal(2)])


if __name__ == "__main__":
    unittest.main()
