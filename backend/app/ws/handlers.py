"""WebSocket event handlers.

Іменування — згідно з CLAUDE.md: `on_<event>`. Кожен хендлер є async і
отримує room_id, user_id та вхідне повідомлення. Всі помилки логуються з
контекстом (room_id, user_id).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from app.models.schemas import WSMessage, WSMessageType
from app.ws.manager import connection_manager

logger = logging.getLogger(__name__)


async def on_user_joined(room_id: str, user_id: str, username: str) -> None:
    """Повідомити кімнаті, що підключився новий студент."""
    msg = WSMessage(
        type=WSMessageType.USER_JOINED,
        userId=user_id,
        username=username,
    )
    await connection_manager.broadcast(room_id, msg)
    logger.info("ws.user_joined", extra={"room_id": room_id, "user_id": user_id})


async def on_user_left(room_id: str, user_id: str) -> None:
    """Повідомити кімнаті про відключення."""
    msg = WSMessage(type=WSMessageType.USER_LEFT, userId=user_id)
    await connection_manager.broadcast(room_id, msg)
    logger.info("ws.user_left", extra={"room_id": room_id, "user_id": user_id})


async def on_git_command(
    room_id: str,
    user_id: str,
    command: str,
    sender: WebSocket,
) -> None:
    """Обробити Git-команду від студента.

    TODO: делегувати `app.git.executor.GitCommandExecutor`, отримати GitEvent
    і транслювати через `connection_manager.broadcast`. Поки що — заглушка,
    яка лише відбиває команду назад у кімнату.
    """
    logger.info(
        "ws.git_command.received",
        extra={"room_id": room_id, "user_id": user_id, "command": command},
    )
    # TODO(executor): викликати executor.run(room_id, command) і надсилати
    #                 реальний GIT_EVENT / GRAPH_UPDATE.
    echo = WSMessage(
        type=WSMessageType.GIT_EVENT,
        action="echo",
        userId=user_id,
        payload={"command": command, "status": "stub"},
    )
    await connection_manager.broadcast(room_id, echo)


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
    err = WSMessage(
        type=WSMessageType.ERROR,
        payload={"reason": "unknown_message_type", "received": raw.get("type")},
    )
    await sender.send_json(err.model_dump(mode="json"))


async def dispatch(
    room_id: str,
    user_id: str,
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
        await on_git_command(room_id, user_id, command, sender)
    else:
        await on_unknown_message(room_id, user_id, raw, sender)
