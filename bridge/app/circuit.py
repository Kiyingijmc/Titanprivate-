"""Circuit breaker for MT5 health.

Tracks consecutive call timeouts. When the failure threshold is exceeded the circuit
opens — MT5 is marked unhealthy, /health reports degraded, and data endpoints return
503 until recovery succeeds. Recovery is attempted via mt5.shutdown() + mt5.initialize()
on the next call and is single-flighted by an asyncio lock so concurrent requests
don't trigger overlapping recoveries.

The principle: MT5 wedging at the C-extension level is something to detect and
recover from, not something to prevent. The bridge's job is to fail fast and recover
predictably so the trading system gets a clear signal instead of silence.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from .mt5_client import MT5Client
    from .settings import BridgeSettings


class MT5CircuitBreaker:
    """Tracks MT5 health and gates calls when MT5 is wedged."""

    FAILURE_THRESHOLD: int = 3
    SHUTDOWN_TIMEOUT: float = 5.0
    INIT_TIMEOUT: float = 10.0

    def __init__(self) -> None:
        self._consecutive_timeouts: int = 0
        self._healthy: bool = True
        self._recovery_lock: asyncio.Lock = asyncio.Lock()

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def consecutive_timeouts(self) -> int:
        return self._consecutive_timeouts

    def record_success(self) -> None:
        if self._consecutive_timeouts > 0:
            logger.info(
                "MT5 call succeeded; resetting timeout counter from {}", self._consecutive_timeouts
            )
        self._consecutive_timeouts = 0
        self._healthy = True

    def record_timeout(self) -> None:
        self._consecutive_timeouts += 1
        logger.warning(
            "MT5 call timed out ({}/{} consecutive)",
            self._consecutive_timeouts,
            self.FAILURE_THRESHOLD,
        )
        if self._consecutive_timeouts >= self.FAILURE_THRESHOLD and self._healthy:
            logger.error(
                "MT5 circuit OPEN — {} consecutive timeouts; data endpoints will 503 until recovery",
                self._consecutive_timeouts,
            )
            self._healthy = False

    def force_unhealthy(self) -> None:
        """Mark the circuit open without going through the timeout-counting path.

        Used at startup if mt5.initialize() fails or times out — we know MT5 is
        unhealthy without needing 3 client calls to discover it.
        """
        self._healthy = False

    async def attempt_recovery(
        self,
        mt5_client: MT5Client,
        settings: BridgeSettings,
    ) -> bool:
        """Try to recover MT5 via shutdown + reinitialize. Returns True if recovered.

        Single-flighted by an asyncio lock — only one task at a time runs the
        shutdown+initialize sequence. Other tasks waiting on the lock observe the
        post-recovery state and return immediately.
        """
        if self._healthy:
            return True
        async with self._recovery_lock:
            # Double-check after lock acquire — another task may have recovered
            # while we were waiting. Mypy can't reason about concurrent mutation
            # of self._healthy, so it flags the inner branch as unreachable.
            if self._healthy:
                return True  # type: ignore[unreachable]
            logger.warning("MT5 recovery starting: shutdown + reinitialize")
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(mt5_client.shutdown),
                    timeout=self.SHUTDOWN_TIMEOUT,
                )
            except TimeoutError:
                logger.error("MT5 shutdown timed out during recovery; continuing to reinitialize")
            except Exception as e:  # noqa: BLE001 — defensive at recovery boundary
                logger.error("MT5 shutdown raised during recovery: {}", e)
            try:
                ok = await asyncio.wait_for(
                    asyncio.to_thread(
                        mt5_client.initialize,
                        settings.mt5_login,
                        settings.mt5_password,
                        settings.mt5_server,
                        settings.mt5_path,
                    ),
                    timeout=self.INIT_TIMEOUT,
                )
            except TimeoutError:
                logger.error("MT5 reinitialize timed out during recovery")
                return False
            except Exception as e:  # noqa: BLE001 — defensive at recovery boundary
                logger.error("MT5 reinitialize raised during recovery: {}", e)
                return False
            if ok:
                self._healthy = True
                self._consecutive_timeouts = 0
                logger.success("MT5 recovery successful — circuit closed")
                return True
            logger.error("MT5 reinitialize returned False")
            return False
