"""Unit tests for tradebot.core.projection (M0-4).

Covers the ``project(snap); apply tail events`` half of the boot sequence in
docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md §1.3, as a pure fold:
the per-schema reducer registry, accumulation, the two skip rules (no reducer →
logged-and-ignored per §2; ``snapshot.projection`` never re-folded), and the one
bookkeeping field the fold owns (``last_seq``) — pointedly *not* ``row_hash``,
which an ``Envelope`` does not carry and only ``EventLog`` can compute.

No concrete event family is exercised, because none exists yet: §1.2's
``market.*``/``order.*`` schemas are design-doc only and are not registered in
``tradebot/core/events.py``. Everything here runs against synthetic schemas.

NOTE ON LOCATION: this file lives directly under tests/unit/ (flat, like every
other test module here) rather than under tests/unit/tradebot/. A test package
named `tradebot` would shadow the real top-level `tradebot` package during
`unittest discover -s tests/unit`, so `import tradebot.core.projection` would
resolve to the test package and every case here would error out. (Same
precedent as tests/unit/test_tradebot_events.py, S003/M0-2, and
tests/unit/test_tradebot_event_log.py, S004/M0-3.)
"""

import ast
import unittest
from pathlib import Path

from tradebot.core import projection
from tradebot.core.event_log import SNAPSHOT_SCHEMA as EVENT_LOG_SNAPSHOT_SCHEMA
from tradebot.core.events import Envelope

CANDLE = "test.candle_closed"
UNMAPPED = "test.no_reducer_here"

BASE_TS = 1_700_000_000_000_000_000


def make_envelope(schema, seq, **payload):
    return Envelope(
        schema=schema,
        schema_version=1,
        ts_event=BASE_TS + (seq or 0),
        ts_ingest=BASE_TS + (seq or 0),
        actor="core",
        payload=payload,
        seq=seq,
    )


def count_candles(state, envelope):
    """A reducer that copies the nested container it touches (the documented rule)."""
    bars = dict(state.get("bars") or {})
    instrument = envelope.payload["instrument"]
    bars[instrument] = bars.get(instrument, 0) + 1
    state["bars"] = bars
    return state


class ProjectionTestCase(unittest.TestCase):
    """Every case runs inside a scoped registry, so nothing leaks between tests."""

    def setUp(self):
        scope = projection.reducer_scope()
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)


class TestReducerRegistry(ProjectionTestCase):
    def test_register_reducer_binds_a_schema(self):
        projection.register_reducer(CANDLE)(count_candles)

        self.assertIs(projection.reducer_for(CANDLE), count_candles)
        self.assertIn(CANDLE, projection.registered_schemas())

    def test_decorator_returns_the_function_unchanged(self):
        @projection.register_reducer(CANDLE)
        def reducer(state, envelope):
            return state

        self.assertIs(projection.reducer_for(CANDLE), reducer)

    def test_unknown_schema_has_no_reducer(self):
        self.assertIsNone(projection.reducer_for(UNMAPPED))

    def test_re_registering_the_same_function_is_a_no_op(self):
        projection.register_reducer(CANDLE)(count_candles)
        projection.register_reducer(CANDLE)(count_candles)

        self.assertIs(projection.reducer_for(CANDLE), count_candles)

    def test_a_conflicting_second_reducer_is_refused(self):
        projection.register_reducer(CANDLE)(count_candles)

        def other(state, envelope):  # pragma: no cover - never invoked
            return state

        with self.assertRaises(ValueError):
            projection.register_reducer(CANDLE)(other)
        self.assertIs(projection.reducer_for(CANDLE), count_candles)

    def test_reducer_scope_restores_the_registry(self):
        self.assertIsNone(projection.reducer_for(CANDLE))
        with projection.reducer_scope():
            projection.register_reducer(CANDLE)(count_candles)
            self.assertIsNotNone(projection.reducer_for(CANDLE))
        self.assertIsNone(projection.reducer_for(CANDLE))


class TestFold(ProjectionTestCase):
    def setUp(self):
        super().setUp()
        projection.register_reducer(CANDLE)(count_candles)

    def test_fold_accumulates_over_a_registered_schema(self):
        events = [
            make_envelope(CANDLE, 1, instrument="EURUSD"),
            make_envelope(CANDLE, 2, instrument="EURUSD"),
            make_envelope(CANDLE, 3, instrument="XAUUSD"),
        ]

        state = projection.fold(events)

        self.assertEqual(state["bars"], {"EURUSD": 2, "XAUUSD": 1})

    def test_an_empty_stream_folds_to_the_seeded_state(self):
        self.assertEqual(projection.fold([]), {projection.LAST_SEQ: 0})

    def test_a_schema_with_no_reducer_is_skipped_not_an_error(self):
        events = [
            make_envelope(CANDLE, 1, instrument="EURUSD"),
            make_envelope(UNMAPPED, 2, whatever=True),
            make_envelope(CANDLE, 3, instrument="EURUSD"),
        ]

        state = projection.fold(events)

        self.assertEqual(state["bars"], {"EURUSD": 2})
        self.assertNotIn("whatever", state)

    def test_snapshot_rows_are_never_refolded(self):
        # Even with a reducer deliberately bound to the snapshot schema, fold
        # must not run it: a snapshot is derived from prior folding, so folding
        # it again would double-count the history it summarises.
        calls = []

        @projection.register_reducer(projection.SNAPSHOT_SCHEMA)
        def explode(state, envelope):  # pragma: no cover - must never run
            calls.append(envelope)
            state["refolded"] = True
            return state

        events = [
            make_envelope(CANDLE, 1, instrument="EURUSD"),
            make_envelope(projection.SNAPSHOT_SCHEMA, 2, state={"bars": {"EURUSD": 99}}),
            make_envelope(CANDLE, 3, instrument="EURUSD"),
        ]

        state = projection.fold(events)

        self.assertEqual(calls, [])
        self.assertNotIn("refolded", state)
        self.assertEqual(state["bars"], {"EURUSD": 2})

    def test_a_reducer_may_mutate_in_place_and_return_none(self):
        @projection.register_reducer(UNMAPPED)
        def in_place(state, envelope):
            state["touched"] = state.get("touched", 0) + 1
            return None

        state = projection.fold([make_envelope(UNMAPPED, 1), make_envelope(UNMAPPED, 2)])

        self.assertEqual(state["touched"], 2)

    def test_a_reducer_may_return_a_fresh_dict(self):
        @projection.register_reducer(UNMAPPED)
        def replace(state, envelope):
            return {"generation": state.get("generation", 0) + 1}

        state = projection.fold([make_envelope(UNMAPPED, 1), make_envelope(UNMAPPED, 2)])

        self.assertEqual(state["generation"], 2)
        self.assertEqual(state[projection.LAST_SEQ], 2)


class TestFoldState(ProjectionTestCase):
    def setUp(self):
        super().setUp()
        projection.register_reducer(CANDLE)(count_candles)

    def test_a_caller_supplied_state_is_the_starting_point(self):
        initial = {"bars": {"EURUSD": 10}, projection.LAST_SEQ: 7}

        state = projection.fold([make_envelope(CANDLE, 8, instrument="EURUSD")], initial)

        self.assertEqual(state["bars"], {"EURUSD": 11})
        self.assertEqual(state[projection.LAST_SEQ], 8)

    def test_folding_does_not_mutate_the_state_it_was_handed(self):
        initial = {"bars": {"EURUSD": 10}, projection.LAST_SEQ: 7}

        projection.fold([make_envelope(CANDLE, 8, instrument="EURUSD")], initial)

        self.assertEqual(initial, {"bars": {"EURUSD": 10}, projection.LAST_SEQ: 7})

    def test_last_seq_tracks_the_highest_seq_consumed(self):
        state = projection.fold(
            [
                make_envelope(CANDLE, 1, instrument="EURUSD"),
                make_envelope(CANDLE, 2, instrument="EURUSD"),
            ]
        )

        self.assertEqual(state[projection.LAST_SEQ], 2)

    def test_last_seq_advances_past_skipped_rows_too(self):
        # A tail of not-yet-mapped schemas still happened. If the watermark
        # stalled behind them, a resume from last_seq+1 would re-offer them
        # forever.
        state = projection.fold(
            [
                make_envelope(CANDLE, 1, instrument="EURUSD"),
                make_envelope(UNMAPPED, 2),
                make_envelope(projection.SNAPSHOT_SCHEMA, 3, state={}),
            ]
        )

        self.assertEqual(state[projection.LAST_SEQ], 3)

    def test_envelopes_without_a_seq_leave_the_watermark_alone(self):
        state = projection.fold(
            [
                make_envelope(CANDLE, 4, instrument="EURUSD"),
                make_envelope(CANDLE, None, instrument="EURUSD"),
            ]
        )

        self.assertEqual(state[projection.LAST_SEQ], 4)
        self.assertEqual(state["bars"], {"EURUSD": 2})

    def test_the_watermark_never_goes_backward(self):
        state = projection.fold(
            [make_envelope(CANDLE, 2, instrument="EURUSD")],
            {projection.LAST_SEQ: 9},
        )

        self.assertEqual(state[projection.LAST_SEQ], 9)

    def test_the_folded_state_carries_no_chain_hash_fields(self):
        # The Envelope has no row_hash to fold (tradebot/core/events.py §1.1
        # minus the writer-computed fields), so the projection must not invent
        # one. EventLog.head()/verify_chain() stay the only source of the head.
        state = projection.fold(
            [
                make_envelope(CANDLE, 1, instrument="EURUSD"),
                make_envelope(projection.SNAPSHOT_SCHEMA, 2, state={}, chain_head={"seq": 1}),
            ]
        )

        self.assertEqual(set(state), {"bars", projection.LAST_SEQ})
        for forbidden in ("row_hash", "prev_hash", "chain_head"):
            self.assertNotIn(forbidden, state)


class TestModuleIsPure(unittest.TestCase):
    """projection.py must stay a pure function over Envelopes."""

    def imported_modules(self):
        tree = ast.parse(Path(projection.__file__).read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
        return modules

    def test_projection_does_not_import_sqlite3_or_the_event_log(self):
        modules = self.imported_modules()

        self.assertNotIn("sqlite3", modules)
        self.assertFalse(
            [m for m in modules if m.startswith("tradebot.core.event_log")],
            f"projection must not import the event log; imports were {sorted(modules)}",
        )

    def test_snapshot_schema_matches_the_event_log_constant(self):
        # projection.py redeclares the constant rather than importing it (that
        # import would drag sqlite3 in). This is the guard that keeps the two
        # spellings from drifting apart.
        self.assertEqual(projection.SNAPSHOT_SCHEMA, EVENT_LOG_SNAPSHOT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
