"""Typed events for the Titan event bus (Trading OS B0).

Frozen dataclasses; JSON-scalar fields only, so every event serializes
losslessly to the event journal (the golden tape) and back.
"""
from dataclasses import dataclass, asdict, fields
from typing import ClassVar, Optional

EVENT_TYPES: dict = {}


def _register(cls):
    EVENT_TYPES[cls.name] = cls
    return cls


@dataclass(frozen=True)
class Event:
    name: ClassVar[str] = "Event"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evt"] = type(self).name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Optional["Event"]:
        target = EVENT_TYPES.get(d.get("evt"))
        if target is None:
            return None
        keys = {f.name for f in fields(target)}
        return target(**{k: v for k, v in d.items() if k in keys})


@_register
@dataclass(frozen=True)
class BarClosed(Event):
    name: ClassVar[str] = "BarClosed"
    symbol: str = ""
    tf: str = ""
    bar_time: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0


@_register
@dataclass(frozen=True)
class TickReceived(Event):
    name: ClassVar[str] = "TickReceived"
    symbol: str = ""
    bid: float = 0.0


@_register
@dataclass(frozen=True)
class HeartbeatReceived(Event):
    name: ClassVar[str] = "HeartbeatReceived"
    balance: float = 0.0
    equity: float = 0.0
    n_positions: int = 0
    n_orders: int = 0


@_register
@dataclass(frozen=True)
class ExecutionReceived(Event):
    name: ClassVar[str] = "ExecutionReceived"
    status: str = ""
    ticket: int = 0
    symbol: str = ""
    pnl: float = 0.0


@_register
@dataclass(frozen=True)
class SpecsUpdated(Event):
    name: ClassVar[str] = "SpecsUpdated"
    symbol: str = ""
    tick_value: float = 0.0
    tick_size: float = 0.0
    vol_min: float = 0.0
    vol_step: float = 0.0


@_register
@dataclass(frozen=True)
class SystemStateChanged(Event):
    name: ClassVar[str] = "SystemStateChanged"
    state: str = ""


@_register
@dataclass(frozen=True)
class WarmupSnapshot(Event):
    name: ClassVar[str] = "WarmupSnapshot"
    symbol: str = ""
    tf: str = ""
    n_bars: int = 0
    path: str = ""
    sha256: str = ""
