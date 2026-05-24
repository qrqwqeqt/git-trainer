"""Unit-тести метрик (GitCommandMetrics) та ConnectionManager.stats()."""
from __future__ import annotations

from app.metrics import GitCommandMetrics
from app.ws.manager import ConnectionManager


def test_empty_snapshot_is_zeroed():
    m = GitCommandMetrics()
    snap = m.snapshot()
    assert snap.count == 0
    assert snap.avg_ms == 0.0
    assert snap.max_ms == 0.0
    assert m.total == 0
    assert m.failed == 0


def test_record_counts_total_and_failed():
    m = GitCommandMetrics()
    m.record(10.0, failed=False)
    m.record(20.0, failed=True)
    m.record(30.0, failed=False)
    assert m.total == 3
    assert m.failed == 1


def test_snapshot_percentiles_and_avg():
    m = GitCommandMetrics()
    for v in range(1, 101):  # 1..100 мс
        m.record(float(v), failed=False)
    snap = m.snapshot()
    assert snap.count == 100
    assert snap.avg_ms == 50.5
    assert snap.max_ms == 100.0
    # nearest-rank на рівномірному 1..100
    assert snap.p50_ms == 50.0
    assert snap.p95_ms == 95.0
    assert snap.p99_ms == 99.0


def test_ring_buffer_caps_samples_but_not_totals():
    m = GitCommandMetrics(max_samples=10)
    for _ in range(25):
        m.record(5.0, failed=False)
    # лічильник total — за весь час; вибірка для перцентилів — обмежена
    assert m.total == 25
    assert m.snapshot().count == 10


def test_reset_clears_everything():
    m = GitCommandMetrics()
    m.record(10.0, failed=True)
    m.reset()
    assert m.total == 0
    assert m.failed == 0
    assert m.snapshot().count == 0


def test_connection_manager_stats_empty():
    cm = ConnectionManager()
    total, rooms = cm.stats()
    assert total == 0
    assert rooms == 0
