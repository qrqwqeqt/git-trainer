"""In-memory менеджер WebSocket-з'єднань по кімнатах.

Для MVP достатньо зберігати стан у пам'яті одного процесу. При масштабуванні
замінимо на Redis pub/sub без зміни інтерфейсу.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.models.schemas import WSMessage

logger = logging.getLogger(__name__)


@dataclass
class RoomState:
    """Стан однієї кімнати: активні з'єднання + блокування."""

    connections: set[WebSocket] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    """Тримає множину WS-з'єднань для кожної кімнати та транслює події."""

    def __init__(self) -> None:
        self._rooms: dict[str, RoomState] = defaultdict(RoomState)

    async def connect(self, room_id: str, websocket: WebSocket) -> None:
        """Прийняти WS-з'єднання та зареєструвати його в кімнаті."""
        await websocket.accept()
        room = self._rooms[room_id]
        async with room.lock:
            room.connections.add(websocket)
        logger.info(
            "ws.connected",
            extra={"room_id": room_id, "connections": len(room.connections)},
        )

    async def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        """Видалити з'єднання з кімнати. Безпечно викликати кілька разів."""
        room = self._rooms.get(room_id)
        if room is None:
            return
        async with room.lock:
            room.connections.discard(websocket)
            if not room.connections:
                # Прибираємо порожні кімнати, щоб не тримати stale state.
                self._rooms.pop(room_id, None)
        logger.info("ws.disconnected", extra={"room_id": room_id})

    async def broadcast(
        self,
        room_id: str,
        message: WSMessage,
        *,
        exclude: WebSocket | None = None,
    ) -> None:
        """Розіслати повідомлення всім активним з'єднанням кімнати.

        Якщо передано `exclude`, відправнику повідомлення не дублюється.
        Зламані з'єднання автоматично відкидаються.
        """
        room = self._rooms.get(room_id)
        if room is None:
            return
        payload = message.model_dump(mode="json")
        dead: list[WebSocket] = []
        # Снепшот під локом, щоб broadcast не блокував connect/disconnect.
        async with room.lock:
            targets = [ws for ws in room.connections if ws is not exclude]
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 — broadcast must be resilient
                logger.exception("ws.broadcast_failed", extra={"room_id": room_id})
                dead.append(ws)
        if dead:
            async with room.lock:
                for ws in dead:
                    room.connections.discard(ws)

    def room_size(self, room_id: str) -> int:
        room = self._rooms.get(room_id)
        return len(room.connections) if room else 0


# Модуль-рівневий singleton — імпортуємо у хендлерах і main.py
connection_manager = ConnectionManager()
