"""tradebot.core.events — event envelope, schema registry, canonical JSON,
upcasters (M0-2).

See docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md §1.1 (the
envelope) and §4.2/F-038 (canonical JSON). This module owns the envelope
shape minus the two fields only the event log's sole writer computes
(``prev_hash``/``row_hash`` — ``event_log.py``, M0-3) and the canonical JSON
helper that ``features/registry.py``'s future ``params_hash`` (M1) will
reuse rather than reimplement.

``tradebot`` is an independent package from ``src/`` (the Titan v14 bot);
this module follows ``src/core/events.py``'s ``EVENT_TYPES``/``_register``/
``from_dict`` pattern as prior art for shape only — it does not import from
that module.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------------------
# UUIDv7 (RFC 9562) — stdlib-only, no third-party uuid6/uuid7 dependency.
# ---------------------------------------------------------------------------


def uuid7() -> str:
    """Generate a time-ordered RFC 9562 UUIDv7 string."""
    unix_ts_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits of randomness
    rand_a = (rand >> 68) & 0xFFF  # top 12 bits -> the 12-bit rand_a field
    rand_b = rand & ((1 << 62) - 1)  # low 62 bits -> the 62-bit rand_b field

    value = (unix_ts_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version nibble (0111)
    value |= rand_a << 64
    value |= 0b10 << 62  # variant bits (10)
    value |= rand_b

    hex_str = f"{value:032x}"
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


# ---------------------------------------------------------------------------
# Canonical JSON (F-038): sorted keys, NaN/Infinity forbidden, numerics
# normalized (int-valued floats emitted as ints, no exponent notation,
# -0 -> 0).
# ---------------------------------------------------------------------------


def canonical_json(payload: dict) -> str:
    return _encode(payload)


def _encode(obj) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        return json.dumps(obj)
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return _encode_float(obj)
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0])
        inner = ",".join(f"{json.dumps(k)}:{_encode(v)}" for k, v in items)
        return "{" + inner + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_encode(v) for v in obj) + "]"
    raise TypeError(f"canonical_json: unsupported type {type(obj)!r}")


def _encode_float(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"canonical_json: non-finite float {value!r} is not allowed")
    if value == 0.0:
        return "0"
    if value.is_integer():
        return str(int(value))
    text = repr(value)
    if "e" not in text and "E" not in text:
        return text
    text = f"{value:.17f}".rstrip("0")
    return text if not text.endswith(".") else text + "0"


# ---------------------------------------------------------------------------
# Schema registry + upcasters
# ---------------------------------------------------------------------------

_REGISTRY: dict[tuple[str, int], type] = {}
_CURRENT_VERSION: dict[str, int] = {}
_UPCASTERS: dict[tuple[str, int], Callable[[dict], dict]] = {}


def register(schema: str, version: int):
    """Decorator registering a payload type for ``(schema, version)``."""

    def decorator(payload_cls):
        _REGISTRY[(schema, version)] = payload_cls
        if version > _CURRENT_VERSION.get(schema, 0):
            _CURRENT_VERSION[schema] = version
        return payload_cls

    return decorator


def register_upcaster(schema: str, from_version: int):
    """Decorator registering an upgrade fn from ``from_version`` to the next."""

    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _UPCASTERS[(schema, from_version)] = fn
        return fn

    return decorator


def payload_type(schema: str, version: int) -> type | None:
    return _REGISTRY.get((schema, version))


def current_schema_version(schema: str, default: int) -> int:
    return _CURRENT_VERSION.get(schema, default)


def upcast_payload(schema: str, payload: dict, from_version: int) -> tuple[int, dict]:
    """Chain registered upcasters until ``schema``'s current version is reached."""
    version = from_version
    target = _CURRENT_VERSION.get(schema, from_version)
    while version < target:
        upgrade = _UPCASTERS.get((schema, version))
        if upgrade is None:
            break
        payload = upgrade(payload)
        version += 1
    return version, payload


# ---------------------------------------------------------------------------
# Envelope (pass3-systems.md §1.1, minus prev_hash/row_hash — event_log.py's
# job, M0-3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Envelope:
    schema: str
    schema_version: int
    ts_event: int
    ts_ingest: int
    actor: str
    payload: dict = field(hash=False)
    event_id: str = field(default_factory=uuid7)
    correlation_id: str | None = None
    parent_ids: tuple[str, ...] = ()
    idempotency_key: str | None = None
    seq: int | None = None


def envelope_to_dict(env: Envelope) -> dict:
    return {
        "event_id": env.event_id,
        "schema": env.schema,
        "schema_version": env.schema_version,
        "ts_event": env.ts_event,
        "ts_ingest": env.ts_ingest,
        "correlation_id": env.correlation_id,
        "parent_ids": list(env.parent_ids),
        "idempotency_key": env.idempotency_key,
        "actor": env.actor,
        "payload": env.payload,
        "seq": env.seq,
    }


def envelope_from_dict(d: dict) -> Envelope:
    schema = d["schema"]
    version, payload = upcast_payload(schema, d["payload"], d["schema_version"])
    return Envelope(
        schema=schema,
        schema_version=version,
        ts_event=d["ts_event"],
        ts_ingest=d["ts_ingest"],
        actor=d["actor"],
        payload=payload,
        event_id=d["event_id"],
        correlation_id=d.get("correlation_id"),
        parent_ids=tuple(d.get("parent_ids") or ()),
        idempotency_key=d.get("idempotency_key"),
        seq=d.get("seq"),
    )


def encode_envelope(env: Envelope) -> str:
    return canonical_json(envelope_to_dict(env))


def decode_envelope(data: str) -> Envelope:
    return envelope_from_dict(json.loads(data))
