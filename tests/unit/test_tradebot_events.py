"""Unit tests for tradebot.core.events (M0-2).

Covers the event envelope, canonical JSON (F-038), the schema registry, and
upcasters from docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md
§1.1 and §4.2/P7.

NOTE ON LOCATION: this file lives directly under tests/unit/ (flat, like every
other test module here) rather than under tests/unit/tradebot/. A test package
named `tradebot` would shadow the real top-level `tradebot` package during
`unittest discover -s tests/unit`, so `import tradebot.core.events` would
resolve to the test package (which has no `core`) and every case here would
error out. Keeping the file flat lets the import resolve to the real package
via the repo root on sys.path. (Same precedent as tests/unit/test_config_schema.py,
S001/M0-1.)
"""

import unittest

from tradebot.core import events as events_module
from tradebot.core.events import (
    Envelope,
    canonical_json,
    decode_envelope,
    encode_envelope,
    register,
    register_upcaster,
    uuid7,
)


class TestUuid7(unittest.TestCase):
    def test_shape_has_correct_version_and_variant_bits(self):
        value = uuid7()
        # xxxxxxxx-xxxx-7xxx-{8,9,a,b}xxx-xxxxxxxxxxxx
        self.assertRegex(
            value,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )

    def test_generates_unique_values(self):
        ids = [uuid7() for _ in range(200)]
        self.assertEqual(len(ids), len(set(ids)))


class TestCanonicalJson(unittest.TestCase):
    def test_int_and_equivalent_float_collide(self):
        self.assertEqual(canonical_json({"n": 20}), canonical_json({"n": 20.0}))

    def test_distinct_values_do_not_collide(self):
        self.assertNotEqual(canonical_json({"n": 20}), canonical_json({"n": 21}))

    def test_key_order_does_not_affect_output(self):
        self.assertEqual(canonical_json({"a": 1, "b": 2}), canonical_json({"b": 2, "a": 1}))

    def test_negative_zero_collapses_to_zero(self):
        self.assertEqual(canonical_json({"n": -0.0}), canonical_json({"n": 0}))

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            canonical_json({"n": float("nan")})

    def test_infinity_raises(self):
        with self.assertRaises(ValueError):
            canonical_json({"n": float("inf")})
        with self.assertRaises(ValueError):
            canonical_json({"n": float("-inf")})

    def test_no_exponent_notation_for_small_fractional_floats(self):
        out = canonical_json({"n": 1e-05})
        self.assertNotIn("e", out.lower())


class TestEnvelopeDeterminism(unittest.TestCase):
    @staticmethod
    def _fixed_envelopes():
        return [
            Envelope(
                schema="test.dummy_determinism",
                schema_version=1,
                ts_event=1_700_000_000_000_000_000,
                ts_ingest=1_700_000_000_100_000_000,
                actor="core",
                payload={"n": 20.0, "label": "a"},
                event_id="00000000-0000-7000-8000-000000000001",
                correlation_id="corr-1",
                parent_ids=("parent-1",),
                seq=1,
            ),
            Envelope(
                schema="test.dummy_determinism",
                schema_version=1,
                ts_event=1_700_000_000_200_000_000,
                ts_ingest=1_700_000_000_300_000_000,
                actor="core",
                payload={"n": 21, "label": "b"},
                event_id="00000000-0000-7000-8000-000000000002",
                seq=2,
            ),
        ]

    @staticmethod
    def _round_trip(envelopes):
        encoded = [encode_envelope(e) for e in envelopes]
        decoded = [decode_envelope(s) for s in encoded]
        return [encode_envelope(e) for e in decoded]

    def test_encode_decode_reencode_is_byte_identical_across_two_passes(self):
        envelopes = self._fixed_envelopes()
        pass_one = self._round_trip(envelopes)
        pass_two = self._round_trip(envelopes)
        self.assertEqual(pass_one, pass_two)
        self.assertEqual(pass_one, [encode_envelope(e) for e in envelopes])


class TestUpcasting(unittest.TestCase):
    # The @register/@register_upcaster decorators below write into
    # tradebot.core.events' module-global registries. Without a restore they
    # leak `test.upcast_demo` into every later test module in the same
    # `unittest discover` run (RS003 MINOR). Snapshot + restore in place, so
    # the dicts other modules hold references to stay the same objects.
    def setUp(self):
        self._saved = {
            name: dict(getattr(events_module, name))
            for name in ("_REGISTRY", "_CURRENT_VERSION", "_UPCASTERS")
        }
        self.addCleanup(self._restore_registries)

    def _restore_registries(self):
        for name, saved in self._saved.items():
            live = getattr(events_module, name)
            live.clear()
            live.update(saved)

    def test_v1_payload_upcasts_to_v2_shape_through_the_registry(self):
        schema = "test.upcast_demo"

        @register(schema, 1)
        class PayloadV1:
            pass

        @register(schema, 2)
        class PayloadV2:
            pass

        @register_upcaster(schema, 1)
        def _v1_to_v2(payload: dict) -> dict:
            upgraded = dict(payload)
            upgraded["greeting"] = upgraded.pop("hello")
            return upgraded

        env = Envelope(
            schema=schema,
            schema_version=1,
            ts_event=1,
            ts_ingest=2,
            actor="core",
            payload={"hello": "world"},
        )

        decoded = decode_envelope(encode_envelope(env))

        self.assertEqual(decoded.schema_version, 2)
        self.assertEqual(decoded.payload, {"greeting": "world"})


if __name__ == "__main__":
    unittest.main()
