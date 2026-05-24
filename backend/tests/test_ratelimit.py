"""Unit-тести RateLimiter (sliding-window, без часу реального годинника)."""
from __future__ import annotations

from app.ratelimit import RateLimiter


def test_allows_up_to_limit():
    rl = RateLimiter(max_events=3, window_s=60.0)
    assert rl.allow("room", "u") is True
    assert rl.allow("room", "u") is True
    assert rl.allow("room", "u") is True
    # четвертий за вікно — відхиляється
    assert rl.allow("room", "u") is False


def test_limit_is_per_room_user():
    rl = RateLimiter(max_events=1, window_s=60.0)
    assert rl.allow("room", "u1") is True
    # інший юзер у тій самій кімнаті має власний бюджет
    assert rl.allow("room", "u2") is True
    # та сама пара — вже вичерпано
    assert rl.allow("room", "u1") is False


def test_window_eviction_with_monkeypatched_clock(monkeypatch):
    import app.ratelimit as rlmod

    t = {"now": 1000.0}
    monkeypatch.setattr(rlmod.time, "monotonic", lambda: t["now"])

    rl = RateLimiter(max_events=2, window_s=10.0)
    assert rl.allow("r", "u") is True   # t=1000
    assert rl.allow("r", "u") is True   # t=1000
    assert rl.allow("r", "u") is False  # ліміт вичерпано

    t["now"] = 1011.0  # вийшли за вікно 10с
    assert rl.allow("r", "u") is True   # старі записи витіснені


def test_reset_clears_state():
    rl = RateLimiter(max_events=1, window_s=60.0)
    assert rl.allow("r", "u") is True
    assert rl.allow("r", "u") is False
    rl.reset("r", "u")
    assert rl.allow("r", "u") is True
