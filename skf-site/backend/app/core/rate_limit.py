"""A small in-process sliding-window rate limiter.

State lives in this process only, so with several workers each one counts on
its own; good enough to blunt abuse of anonymous endpoints, not a quota system.
"""

from __future__ import annotations

import math
import time
from collections import deque

from fastapi import Request

from app.core.errors import TooManyRequests


class RateLimiter:
    """Allow at most ``max_calls`` per ``period`` seconds for each key."""

    def __init__(self, max_calls: int, period: float, *, detail: str = "Too many requests. Try again later."):
        self.max_calls = max_calls
        self.period = period
        self.detail = detail
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> None:
        """Record one call for *key*, or raise :class:`TooManyRequests`."""
        now = time.monotonic()
        cutoff = now - self.period
        # Drop keys whose calls have all aged out, so the map cannot grow forever.
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.max_calls:
            retry_after = max(1, math.ceil(hits[0] + self.period - now))
            raise TooManyRequests(self.detail, headers={"Retry-After": str(retry_after)})
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


def client_ip(request: Request) -> str:
    """The caller's address.

    Behind the hosting proxy every connection comes from the proxy, so the
    last ``X-Forwarded-For`` hop (the one the proxy appended, not the
    client-supplied ones before it) identifies the caller.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"
