"""Простий in-memory rate-limiter для git-команд (захист від флуду/DoS).

Sliding-window на (room_id, user_id): тримаємо timestamps останніх запитів,
відкидаємо старші за вікно. Для MVP одного процесу достатньо; при масштабуванні
замінюється на Redis без зміни інтерфейсу. Частина підрозділу ПЗ «захист даних».
"""
from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding-window лічильник: не більше `max_events` за `window_s` секунд."""

    def __init__(self, max_events: int, window_s: float) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(self, room_id: str, user_id: str) -> bool:
        """True якщо запит у межах ліміту (і реєструє його). Інакше False."""
        key = (room_id, user_id)
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_events:
            return False
        bucket.append(now)
        return True

    def reset(self, room_id: str | None = None, user_id: str | None = None) -> None:
        """Скинути стан (для тестів або при відключенні користувача)."""
        if room_id is None or user_id is None:
            self._hits.clear()
        else:
            self._hits.pop((room_id, user_id), None)
