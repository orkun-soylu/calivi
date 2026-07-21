"""Brute-force protection — an in-process sliding-window counter.

The scope is deliberately narrow: with a single backend process the counter lives in
memory (no Redis). **A restart resets the counters** — acceptable, because an attacker has
no way to trigger one.

Keying is **by account only** (not IP): nginx does not forward X-Forwarded-For on `/api/`
and uvicorn does not run with `--proxy-headers`, so `request.client.host` is identical for
every user (the nginx container). To key by IP that chain must be fixed first; see
ARCHITECTURE.md "Brute-force protection".
"""
import time
from collections import deque

# Keeps the counter dict from growing without bound: stale keys are swept above this size.
_SWEEP_THRESHOLD = 1000


class SlidingWindowLimiter:
    """Allows `max_attempts` failures within a `window`-second sliding window."""

    def __init__(self, max_attempts: int, window: float) -> None:
        self.max_attempts = max_attempts
        self.window = window
        self._events: dict[str, deque[float]] = {}

    def _live(self, key: str, now: float) -> deque[float]:
        """The key's attempts inside the window (stale ones dropped)."""
        events = self._events.get(key)
        if events is None:
            return deque()
        while events and now - events[0] >= self.window:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def retry_after(self, key: str) -> int:
        """Seconds remaining while locked out (>0), otherwise 0."""
        now = time.monotonic()
        events = self._live(key, now)
        if len(events) < self.max_attempts:
            return 0
        # A new attempt becomes available once the oldest one falls out of the window.
        return max(1, int(self.window - (now - events[0])) + 1)

    def record(self, key: str) -> None:
        """Counts one event against the key. 'Failure' is just the login use-case — the
        registration limiter counts *creations* through the same machinery."""
        now = time.monotonic()
        events = self._live(key, now)
        events.append(now)
        self._events[key] = events
        if len(self._events) > _SWEEP_THRESHOLD:
            self._sweep(now)

    def record_failure(self, key: str) -> None:
        self.record(key)

    def reset(self, key: str) -> None:
        """Called on a successful login so a legitimate user is not punished for earlier typos."""
        self._events.pop(key, None)

    def _sweep(self, now: float) -> None:
        for key in [k for k, e in self._events.items() if not e or now - e[-1] >= self.window]:
            self._events.pop(key, None)

    def clear(self) -> None:
        """For tests only."""
        self._events.clear()


def login_key(identifier: str) -> str:
    """Account key — normalised so case or whitespace differences cannot bypass the counter."""
    return identifier.strip().lower()
