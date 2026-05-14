"""Smoke-тести: /health REST + WebSocket broadcast/error/git-command.

Ці тести мають запускатись БЕЗ реального docker-daemon-а — sandbox_manager
підмінюється фейком у фікстурі `fake_sandbox` (з conftest.py).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.docker.sandbox import ExecResult


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


def test_websocket_git_status_no_graph_update(app, fake_sandbox) -> None:
    """git status — read-only: GIT_EVENT приходить, GRAPH_UPDATE — ні."""
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
        assert evt["action"] == "status"
        assert evt["userId"] == "u1"
        assert evt["payload"]["command"] == "git status"
        assert evt["payload"]["argv"] == ["git", "status"]
        assert evt["payload"]["exit_code"] == 0
        assert evt["payload"]["stdout"] == "On branch main\n"

    # exec викликався лише раз — для status; graph refresh не йшов.
    assert fake_sandbox.exec.call_count == 1


def test_websocket_git_commit_triggers_graph_update(app, fake_sandbox) -> None:
    """git commit — write-команда: спочатку GIT_EVENT, потім GRAPH_UPDATE."""
    fake_sandbox.exec.side_effect = [
        ExecResult(exit_code=0, stdout="[main abc123] init\n", stderr=""),
        # log refresh: один рут-комміт
        ExecResult(
            exit_code=0, stdout="abc123||HEAD -> main|init\n", stderr=""
        ),
    ]
    client = TestClient(app)
    with client.websocket_connect("/ws/r2?user_id=u1&username=U1") as ws:
        _ = ws.receive_json()  # USER_JOINED
        ws.send_json(
            {
                "type": "GIT_COMMAND",
                "payload": {"command": "git commit -m init"},
            }
        )
        evt = ws.receive_json()
        assert evt["type"] == "GIT_EVENT"
        assert evt["action"] == "commit"
        assert evt["payload"]["exit_code"] == 0

        graph_msg = ws.receive_json()
        assert graph_msg["type"] == "GRAPH_UPDATE"
        nodes = graph_msg["graph"]["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["id"] == "abc123"
        assert nodes[0]["branch"] == "main"


def test_websocket_snapshot_sent_to_late_joiner(app, fake_sandbox) -> None:
    """Якщо у кімнаті вже є sandbox з коммітами, новий клієнт має одразу
    отримати GRAPH_UPDATE snapshot після USER_JOINED — без чекання нової
    команди.
    """
    # Імітуємо, що sandbox для кімнати вже існує.
    fake_sandbox.get.return_value = MagicMock()
    # `git log --all` повертає одну ноду.
    fake_sandbox.exec.return_value = ExecResult(
        exit_code=0,
        stdout="abc123||HEAD -> main|init\n",
        stderr="",
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/r-snap?user_id=late&username=Late") as ws:
        first = ws.receive_json()
        assert first["type"] == "USER_JOINED"
        snap = ws.receive_json()
        assert snap["type"] == "GRAPH_UPDATE"
        assert len(snap["graph"]["nodes"]) == 1
        assert snap["graph"]["nodes"][0]["id"] == "abc123"


def test_websocket_no_snapshot_when_sandbox_absent(app, fake_sandbox) -> None:
    """Якщо sandbox-у ще немає (ніхто не вводив команд) — snapshot не шлемо."""
    fake_sandbox.get.return_value = None

    client = TestClient(app)
    with client.websocket_connect("/ws/r-empty?user_id=first&username=First") as ws:
        first = ws.receive_json()
        assert first["type"] == "USER_JOINED"
        # Більше нічого приходити не має (snapshot пропускається).
        # Перевіряємо, що exec не викликався — він був би тільки для snapshot.
        fake_sandbox.exec.assert_not_called()


def test_websocket_invalid_git_command_replies_error(app, fake_sandbox) -> None:
    """Невалідна команда (поза whitelist) → ERROR лише відправнику."""
    client = TestClient(app)
    with client.websocket_connect("/ws/r3?user_id=u1&username=U1") as ws:
        _ = ws.receive_json()  # USER_JOINED
        ws.send_json(
            {
                "type": "GIT_COMMAND",
                "payload": {"command": "git push origin main"},
            }
        )
        err = ws.receive_json()
        assert err["type"] == "ERROR"
        assert err["payload"]["reason"] == "invalid_command"
    # Команда відхилена ще на валідації — exec не запускався.
    fake_sandbox.exec.assert_not_called()


def test_websocket_unknown_message(app) -> None:
    """Невідомий тип — сервер відповідає ERROR безпосередньо відправнику."""
    client = TestClient(app)
    with client.websocket_connect("/ws/r2?user_id=u2&username=U2") as ws:
        _ = ws.receive_json()  # USER_JOINED
        ws.send_json({"type": "WAT", "payload": {}})
        err = ws.receive_json()
        assert err["type"] == "ERROR"
        assert err["payload"]["received"] == "WAT"
