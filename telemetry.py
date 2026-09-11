"""Thread-safe operational metrics that never contain research content."""

from __future__ import annotations
import threading
import time
from collections import Counter
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._duration_total = 0.0

    def increment(self, name: str) -> None:
        with self._lock:
            self._counts[name] += 1

    def observe_job(self, started: float, status: str) -> None:
        with self._lock:
            self._counts[f"jobs_{status}"] += 1
            self._duration_total += max(0.0, time.monotonic() - started)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            completed = self._counts["jobs_completed"] + self._counts["jobs_failed"]
            return {
                "counts": dict(self._counts),
                "job_duration_seconds_total": round(self._duration_total, 3),
                "job_duration_seconds_average": round(self._duration_total / completed, 3) if completed else 0,
                "content_logging": False,
            }


metrics = Metrics()
