"""In-memory метрики для Розділу 4 (дослідження та експерименти).

Легкий registry у пам'яті процесу: лічильники git-команд + ring-buffer
останніх латентностей для перцентилів. Без зовнішніх залежностей — щоб
ендпоінт /metrics був дешевим і не чіпав Docker daemon.
"""
from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass

# Скільки останніх вимірів тримаємо для обчислення перцентилів.
_MAX_SAMPLES = 1000


@dataclass(frozen=True)
class LatencySnapshot:
    """Знімок статистики латентності (мс) на момент запиту."""

    count: int
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


class GitCommandMetrics:
    """Thread-safe лічильники та латентності виконання git-команд.

    record() кличеться з async-коду після кожного exec; snapshot() —
    з /metrics-ендпоінта. Lock тут радше для майбутнього (docker exec
    у to_thread), наразі все в одному event-loop.
    """

    def __init__(self, max_samples: int = _MAX_SAMPLES) -> None:
        self._lock = threading.Lock()
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._total = 0
        self._failed = 0

    def record(self, duration_ms: float, *, failed: bool) -> None:
        with self._lock:
            self._samples.append(duration_ms)
            self._total += 1
            if failed:
                self._failed += 1

    @property
    def total(self) -> int:
        with self._lock:
            return self._total

    @property
    def failed(self) -> int:
        with self._lock:
            return self._failed

    def snapshot(self) -> LatencySnapshot:
        with self._lock:
            samples = sorted(self._samples)
        if not samples:
            return LatencySnapshot(0, 0.0, 0.0, 0.0, 0.0, 0.0)
        n = len(samples)

        def pct(p: float) -> float:
            # nearest-rank: rank = ceil(p/100 * n), 1-based.
            rank = max(1, min(n, math.ceil(p / 100 * n)))
            return samples[rank - 1]

        return LatencySnapshot(
            count=n,
            avg_ms=sum(samples) / n,
            p50_ms=pct(50),
            p95_ms=pct(95),
            p99_ms=pct(99),
            max_ms=samples[-1],
        )

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._total = 0
            self._failed = 0


# Модуль-рівневий singleton — імпортуємо в executor (record) і main (snapshot).
git_metrics = GitCommandMetrics()
