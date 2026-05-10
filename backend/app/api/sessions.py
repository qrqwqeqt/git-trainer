"""REST endpoints для перегляду активних WS-сесій (адмін/моніторинг)."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.ws.manager import connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/rooms/{room_id}/size")
async def room_size(room_id: str) -> dict[str, int | str]:
    """Скільки клієнтів зараз підключено до кімнати.

    Корисно для health-check дашборду. TODO: додати список user_id, коли
    ConnectionManager почне зберігати профіль підключеного користувача.
    """
    size = connection_manager.room_size(room_id)
    return {"room_id": room_id, "connections": size}
