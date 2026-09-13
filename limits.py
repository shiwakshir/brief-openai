"""Small-process admission control for the restricted pilot."""

from __future__ import annotations
import threading
import time


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        point = time.time() if now is None else now
        with self._lock:
            events = [value for value in self._events.get(key, []) if point - value < self.window]
            if len(events) >= self.limit:
                self._events[key] = events
                return False
            events.append(point)
            self._events[key] = events
            return True
