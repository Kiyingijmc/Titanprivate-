"""tradebot.core.sta — Signal Transition Actor skeleton (M0-5).

pass3-systems.md §2.1 names a single transition owner (F-008 mechanism) as
the thing that will later serialize the full signal lifecycle (SigState /
TransitionCause / signal.* schemas — none of which exist yet, M1+). This
module builds only the generic, schema-agnostic mechanism: a FIFO queue of
transition requests drained by one consumer, so at most one request is ever
being processed at a time — no concurrent handler execution, no lost writes
from two transitions racing each other.

A request is a ``(guard, apply)`` pair. ``guard`` is evaluated *inside* the
consumer, at processing time (not at submission time), so it observes
whatever state changed while the request was queued — that's what makes it
useful for resolving races. A failed guard resolves to a rejected outcome
instead of raising (mirrors "losing requests emit
``confirm.resolved.race_losers``" without inventing that concrete schema).
A passed guard's ``apply()`` builds an ``Envelope`` that gets published
through the injected ``EventBus``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Union

from tradebot.core.bus import EventBus
from tradebot.core.events import Envelope

Guard = Callable[[], Union[bool, Awaitable[bool]]]
Apply = Callable[[], Union[Envelope, Awaitable[Envelope]]]


@dataclass(frozen=True)
class TransitionOutcome:
    accepted: bool
    envelope: Envelope | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _Request:
    guard: Guard
    apply: Apply
    future: "asyncio.Future[TransitionOutcome]"


class SignalTransitionActor:
    """Single transition owner: one FIFO queue, one consumer (pass3 §2.1)."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queue: "asyncio.Queue[_Request]" = asyncio.Queue()
        self._consumer: asyncio.Task | None = None

    def _ensure_consumer(self) -> None:
        if self._consumer is None or self._consumer.done():
            self._consumer = asyncio.ensure_future(self._consume())

    async def submit(self, guard: Guard, apply: Apply) -> TransitionOutcome:
        self._ensure_consumer()
        future: "asyncio.Future[TransitionOutcome]" = asyncio.get_running_loop().create_future()
        await self._queue.put(_Request(guard=guard, apply=apply, future=future))
        return await future

    async def aclose(self) -> None:
        if self._consumer is not None:
            self._consumer.cancel()
            try:
                await self._consumer
            except asyncio.CancelledError:
                pass
            self._consumer = None

    async def _consume(self) -> None:
        while True:
            request = await self._queue.get()
            try:
                outcome = await self._process(request.guard, request.apply)
            except Exception as exc:
                if not request.future.done():
                    request.future.set_exception(exc)
            else:
                if not request.future.done():
                    request.future.set_result(outcome)
            finally:
                self._queue.task_done()

    async def _process(self, guard: Guard, apply: Apply) -> TransitionOutcome:
        passed = guard()
        if asyncio.iscoroutine(passed):
            passed = await passed
        if not passed:
            return TransitionOutcome(accepted=False, reason="race_loser")

        envelope = apply()
        if asyncio.iscoroutine(envelope):
            envelope = await envelope
        self._bus.publish(envelope)
        return TransitionOutcome(accepted=True, envelope=envelope)
