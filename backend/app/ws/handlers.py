"""WebSocket event handlers.

Іменування — згідно з CLAUDE.md: `on_<event>`. Кожен хендлер є async і
отримує room_id, user_id та вхідне повідомлення. Усі помилки логуються з
контекстом (room_id, user_id) і не валять WebSocket-з'єднання — натомість
повертається ERROR-повідомлення відправнику.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from uuid import UUID

from app.config import get_settings
from app.db import get_sessionmaker
from app.db.repository import (
    create_session_row,
    get_or_create_room,
    get_or_create_user,
    log_command,
    mark_session_disconnected,
)
from app.docker import sandbox_manager
from app.docker.sandbox import SandboxError
from app.git.executor import GitCommandError, GitCommandExecutor
from app.models.schemas import WSMessage, WSMessageType
from app.ratelimit import RateLimiter
from app.ws.manager import connection_manager

logger = logging.getLogger(__name__)

# Rate-limiter git-команд (захист від флуду). Налаштування — з config.
_settings = get_settings()
command_rate_limiter = RateLimiter(
    max_events=_settings.rate_limit_max,
    window_s=_settings.rate_limit_window_s,
)

# Best-effort persistence (Session-рядки + аудит) у БД. Вимикається в WS-смоук-
# тестах: під TestClient (anyio portal-loop) async-engine конфліктує з aiosqlite
# на teardown ("Event loop is closed"). Саму persistence/audit-логіку покривають
# прямі тести (test_db_persistence, test_audit).
db_persistence_enabled = True


async def on_user_joined(
    room_id: str,
    user_id: str,
    username: str,
    sender: WebSocket | None = None,
) -> UUID | None:
    """Повідомити кімнаті про підключення, записати Session-рядок у БД.

    Повертає UUID створеної Session-row (або None, якщо запис у БД не вдався —
    у такому разі WS-стрім лишається робочим, persistence просто пропускається).
    db_session_id передаємо назад у websocket_endpoint, щоб on_user_left міг
    закрити саме цей рядок.

    Окрім broadcast USER_JOINED, якщо у кімнаті вже працює sandbox (хтось до
    цього виконував команди) — щойно під’єднаному клієнту надсилаємо приватний
    GRAPH_UPDATE-snapshot, щоб він не бачив порожній граф до наступної команди.
    """
    msg = WSMessage(
        type=WSMessageType.USER_JOINED,
        userId=user_id,
        username=username,
    )
    await connection_manager.broadcast(room_id, msg)
    logger.info("ws.user_joined", extra={"room_id": room_id, "user_id": user_id})

    db_session_id: UUID | None = None
    if db_persistence_enabled:
        try:
            sm = get_sessionmaker()
            async with sm() as db:
                user = await get_or_create_user(db, username=username)
                room = await get_or_create_room(
                    db, slug=room_id, owner_id=user.id, display_name=room_id
                )
                row = await create_session_row(db, room_id=room.id, user_id=user.id)
                await db.commit()
                db_session_id = row.id
        except Exception:  # noqa: BLE001 — persistence не повинна ламати WS-стрім
            logger.exception(
                "ws.user_joined.persist_failed",
                extra={"room_id": room_id, "user_id": user_id},
            )

    if sender is not None:
        await _maybe_send_snapshot(room_id, user_id, sender)

    return db_session_id


async def _maybe_send_snapshot(
    room_id: str, user_id: str, sender: WebSocket
) -> None:
    sandbox = sandbox_manager.get(room_id)
    if sandbox is None:
        return
    executor = GitCommandExecutor(room_id, sandbox_manager)
    try:
        graph = await executor.snapshot_graph()
    except Exception:  # noqa: BLE001 — snapshot не повинен ламати приєднання
        logger.exception(
            "ws.snapshot.failed",
            extra={"room_id": room_id, "user_id": user_id},
        )
        return
    if not graph.nodes:
        return
    snap = WSMessage(type=WSMessageType.GRAPH_UPDATE, graph=graph)
    try:
        await sender.send_json(snap.model_dump(mode="json"))
    except Exception:  # noqa: BLE001 — клієнт міг відключитись між accept і snapshot
        logger.warning(
            "ws.snapshot.send_failed",
            extra={"room_id": room_id, "user_id": user_id},
            exc_info=True,
        )


async def on_user_left(
    room_id: str,
    user_id: str,
    db_session_id: UUID | None = None,
) -> None:
    """Повідомити кімнаті про відключення, закрити Session-рядок у БД.

    db_session_id передається з websocket_endpoint (повернуто on_user_joined).
    Якщо persistence не вдався при joined — db_session_id буде None, тут
    просто пропускаємо update.
    """
    msg = WSMessage(type=WSMessageType.USER_LEFT, userId=user_id)
    await connection_manager.broadcast(room_id, msg)
    logger.info("ws.user_left", extra={"room_id": room_id, "user_id": user_id})

    if db_session_id is None:
        return
    try:
        sm = get_sessionmaker()
        async with sm() as db:
            await mark_session_disconnected(db, db_session_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception(
            "ws.user_left.persist_failed",
            extra={
                "room_id": room_id,
                "user_id": user_id,
                "db_session_id": str(db_session_id),
            },
        )


async def on_git_command(
    room_id: str,
    user_id: str,
    username: str,
    command: str,
    sender: WebSocket,
) -> None:
    """Виконати git-команду в sandbox-контейнері кімнати; повідомити всіх.

    Послідовність:
      1. lazy-start sandbox (idempotent, перший виклик піднімає контейнер).
      2. executor.run(command) → ExecOutcome.
      3. broadcast GIT_EVENT (action, stdout, stderr, exit_code).
      4. Якщо була write-команда і вона успішна — broadcast GRAPH_UPDATE.

    Помилки валідації / sandbox-у віддаються відправнику як ERROR; інші
    учасники кімнати їх не бачать (це private помилка студента).
    """
    logger.info(
        "ws.git_command.received",
        extra={"room_id": room_id, "user_id": user_id, "command": command},
    )

    # Rate-limit: захист від флуду команд (DoS). Перевищення — приватний ERROR.
    if not command_rate_limiter.allow(room_id, user_id):
        logger.warning(
            "ws.git_command.rate_limited",
            extra={"room_id": room_id, "user_id": user_id},
        )
        await _send_error(
            sender,
            "rate_limited",
            f"max {_settings.rate_limit_max} команд за "
            f"{_settings.rate_limit_window_s:.0f}с",
        )
        return

    try:
        await sandbox_manager.start(room_id)
    except SandboxError as exc:
        await _send_error(sender, "sandbox_unavailable", str(exc))
        return

    executor = GitCommandExecutor(
        room_id, sandbox_manager, author_name=username
    )
    try:
        outcome = await executor.run(command)
    except GitCommandError as exc:
        await _send_error(sender, "invalid_command", str(exc))
        return
    except SandboxError as exc:
        await _send_error(sender, "sandbox_error", str(exc))
        return

    git_event = WSMessage(
        type=WSMessageType.GIT_EVENT,
        action=outcome.action,
        userId=user_id,
        payload={
            "command": command,
            "argv": outcome.argv,
            "exit_code": outcome.exit_code,
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
        },
    )
    await connection_manager.broadcast(room_id, git_event)

    if outcome.graph is not None:
        graph_msg = WSMessage(
            type=WSMessageType.GRAPH_UPDATE,
            graph=outcome.graph,
        )
        await connection_manager.broadcast(room_id, graph_msg)

    # Аудит-лог (best-effort): не валимо WS-стрім, якщо БД недоступна.
    if not db_persistence_enabled:
        return
    try:
        sm = get_sessionmaker()
        async with sm() as db:
            await log_command(
                db,
                room_slug=room_id,
                username=username,
                command=command,
                exit_code=outcome.exit_code,
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — аудит не повинен ламати основний потік
        logger.exception(
            "ws.git_command.audit_failed",
            extra={"room_id": room_id, "user_id": user_id},
        )


async def on_unknown_message(
    room_id: str,
    user_id: str,
    raw: dict[str, Any],
    sender: WebSocket,
) -> None:
    """Fallback для невідомих типів повідомлень."""
    logger.warning(
        "ws.unknown_message",
        extra={"room_id": room_id, "user_id": user_id, "raw": raw},
    )
    await _send_error(
        sender,
        "unknown_message_type",
        f"received={raw.get('type')}",
        extra={"received": raw.get("type")},
    )


async def dispatch(
    room_id: str,
    user_id: str,
    username: str,
    raw: dict[str, Any],
    sender: WebSocket,
) -> None:
    """Розподільник: підбирає потрібний on_<event> за полем `type`."""
    msg_type = raw.get("type")
    if msg_type == WSMessageType.GIT_COMMAND:
        command = str(raw.get("payload", {}).get("command", "")).strip()
        if not command:
            await on_unknown_message(room_id, user_id, raw, sender)
            return
        await on_git_command(room_id, user_id, username, command, sender)
    else:
        await on_unknown_message(room_id, user_id, raw, sender)


async def _send_error(
    sender: WebSocket,
    reason: str,
    detail: str,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Відправити ERROR-повідомлення тільки тому, хто його спричинив."""
    payload: dict[str, Any] = {"reason": reason, "detail": detail}
    if extra:
        payload.update(extra)
    msg = WSMessage(type=WSMessageType.ERROR, payload=payload)
    await sender.send_json(msg.model_dump(mode="json"))
