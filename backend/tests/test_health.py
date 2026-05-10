"""Smoke-тести: /health REST + WebSocket echo/broadcast.

Ці тести мають запускатись БЕЗ реальної БД і Docker — усі I/O залежності
в main.py — заглушки.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_root_endpoint(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "git-trainer-backend"


def test_websocket_user_joined_broadcast(app) -> None:
    """Два клієнти в одній кімнаті — другий має побачити USER_JOINED."""
    client = TestClient(app)
    url_a = "/ws/test-room?user_id=alice&username=Alice"
    url_b = "/ws/test-room?user_id=bob&username=Bob"
    with client.websocket_connect(url_a) as ws_a:
        # Перший USER_JOINED для Alice — приходить самій Alice (broadcast шле всім).
        first = ws_a.receive_json()
        assert first["type"] == "USER_JOINED"
        assert first["userId"] == "alice"

        with client.websocket_connect(url_b) as ws_b:
            # Коли приєднався Bob, Alice має отримати нове USER_JOINED.
            joined_for_alice = ws_a.receive_json()
            assert joined_for_alice["type"] == "USER_JOINED"
            assert joined_for_alice["userId"] == "bob"

            # Bob отримує власну подію входу.
            first_for_bob = ws_b.receive_json()
            assert first_for_bob["type"] == "USER_JOINED"
            assert first_for_bob["userId"] == "bob"


def test_websocket_git_command_stub(app) -> None:
    """GIT_COMMAND поки що echo-ається як GIT_EVENT action=echo."""
    client = TestClient(app)
    with client.websocket_connect("/ws/r1?user_id=u1&username=U1") as ws:
        _ = ws.receive_json()  # USER_JOINED для самого себе
        ws.send_json(
            {
                "type": "GIT_COMMAND",
                "payload": {"command": "git status"},
            }
        )
        evt = ws.receive_json()
        assert evt["type"] == "GIT_EVENT"
        assert evt["action"] == "echo"
        assert evt["payload"]["command"] == "git status"


def test_websocket_unknown_message(app) -> None:
    """Невідомий тип — сервер відповідає ERROR безпосередньо відправнику."""
    client = TestClient(app)
    with client.websocket_connect("/ws/r2?user_id=u2&username=U2") as ws:
        _ = ws.receive_json()  # USER_JOINED
        ws.send_json({"type": "WAT", "payload": {}})
        err = ws.receive_json()
        assert err["type"] == "ERROR"
        assert err["payload"]["received"] == "WAT"
