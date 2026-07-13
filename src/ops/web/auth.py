# src/ops/web/auth.py
"""Bearer-token auth (fail-closed), per-IP failure throttling, read-only guard."""
import hmac
import os
import time

from fastapi import HTTPException, Request


class AuthThrottle:
    """>limit bad tokens from one IP inside window_s -> blocked until window rolls."""

    def __init__(self, limit: int = 5, window_s: float = 60.0):
        self._limit = limit
        self._window_s = window_s
        self._failures: dict = {}  # ip -> list[timestamps]

    def _prune(self, ip: str, now: float) -> list:
        hits = [t for t in self._failures.get(ip, []) if now - t < self._window_s]
        self._failures[ip] = hits
        return hits

    def blocked(self, ip: str, now: float | None = None) -> bool:
        return len(self._prune(ip, now if now is not None else time.monotonic())) >= self._limit

    def record_failure(self, ip: str, now: float | None = None) -> None:
        self._prune(ip, now if now is not None else time.monotonic())
        self._failures.setdefault(ip, []).append(now if now is not None else time.monotonic())

    def reset(self) -> None:
        self._failures.clear()


THROTTLE = AuthThrottle()


def token_ok(supplied) -> bool:
    expected = os.environ.get("TITAN_GUI_TOKEN", "") or ""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(supplied), expected)


def _client_ip(request) -> str:
    client = getattr(request, "client", None)
    return getattr(client, "host", "?") or "?"


def require_token(request: Request) -> None:
    """FastAPI dependency: 429 when the caller IP is throttled, 401 on bad token."""
    ip = _client_ip(request)
    if THROTTLE.blocked(ip):
        raise HTTPException(status_code=429, detail="too many auth failures; retry later")
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else None
    if not token_ok(supplied):
        THROTTLE.record_failure(ip)
        raise HTTPException(status_code=401, detail="invalid or missing token")


def require_writable() -> None:
    """FastAPI dependency: 403 on all mutating routes in read-only mode."""
    if os.environ.get("TITAN_GUI_READONLY", "") == "1":
        raise HTTPException(status_code=403, detail="read-only mode")
