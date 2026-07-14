"""Polite rate limiting for scraping backends (plan §4.3)."""

import random
import time
from collections.abc import Callable, Iterator
from typing import TypeVar

T = TypeVar("T")


class RateLimiter:
    """Enforce a minimum interval (plus jitter) between calls."""

    def __init__(self, min_interval_s: float, jitter_s: float = 0.5) -> None:
        self.min_interval_s = min_interval_s
        self.jitter_s = jitter_s
        self._next_allowed = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next_allowed:
            time.sleep(self._next_allowed - now)
        self._next_allowed = (
            time.monotonic() + self.min_interval_s + random.uniform(0, self.jitter_s)
        )


def backoff_delays(
    base_s: float = 5.0, factor: float = 2.0, max_delay_s: float = 120.0, tries: int = 4
) -> Iterator[float]:
    delay = base_s
    for _ in range(tries):
        yield min(delay, max_delay_s)
        delay *= factor


def with_retries(fn: Callable[[], T], *, tries: int = 3, base_s: float = 5.0) -> T:
    """Call ``fn``, retrying with exponential backoff on any exception."""
    delays = backoff_delays(base_s=base_s, tries=tries - 1)
    while True:
        try:
            return fn()
        except Exception:
            delay = next(delays, None)
            if delay is None:
                raise
            time.sleep(delay)
