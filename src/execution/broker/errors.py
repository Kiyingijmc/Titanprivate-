"""Typed broker errors. Trading code catches these, never raw httpx/MT5 errors."""
from __future__ import annotations


class BrokerError(Exception):
    """Base for all broker-related errors."""


class BrokerConnectionError(BrokerError):
    """Network/transport failure reaching the bridge. Safe to retry reads; never writes."""


class BrokerAuthError(BrokerError):
    """Auth failure (bad/missing token)."""


class BrokerNotFoundError(BrokerError):
    """Requested resource (symbol, position, order) does not exist."""
