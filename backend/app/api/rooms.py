"""REST endpoints для управління кімнатами.

CRUD на кімнати (list/get/create/delete) — заглушки до Phase 2.4. Поки
що реалізовано лише `DELETE /rooms/{slug}/sandbox` для скидання sandbox-у
з UI.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status

from app.docker import sandbox_manager
from app.docker.sandbox import SandboxError
from app.models.schemas import GraphPayload, RoomCreate, RoomRead, WSMessage, WSMessageType
from app.ws.manager import connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("", response_model=list[RoomRead])
async def list_rooms() -> list[RoomRead]:
    """Повернути список активних кімнат. TODO: читати з БД."""
    return []


@router.post("", response_model=RoomRead, status_code=status.HTTP_201_CREATED)
async def create_room(payload: RoomCreate) -> RoomRead:
    """Створити кімнату + Docker sandbox. TODO: інтеграція з SandboxManager."""
    logger.info("rooms.create.stub", extra={"name": payload.name})
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="create_room not implemented yet",
    )


@router.get("/{room_id}", response_model=RoomRead)
async def get_room(room_id: str) -> RoomRead:
    """Отримати кімнату за ID. TODO: читати з БД."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"room {room_id} not found (stub)",
    )


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_room(room_id: str) -> Response:
    """Видалити кімнату і зупинити sandbox. TODO."""
    logger.info("rooms.delete.stub", extra={"room_id": room_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{slug}/sandbox",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def reset_sandbox(slug: str) -> Response:
    """Зупинити sandbox-контейнер кімнати; наступна git-команда створить новий.

    Корисно з UI, коли студент хоче «почати з нуля», не пересоздаючи
    кімнату. Усім підключеним клієнтам розсилається GRAPH_UPDATE з
    порожнім графом, щоб UI миттєво очистився.
    """
    try:
        await sandbox_manager.stop(slug)
    except SandboxError as exc:
        logger.warning(
            "rooms.reset.failed", extra={"room": slug, "reason": str(exc)}
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"failed to stop sandbox: {exc}",
        ) from exc

    empty = WSMessage(type=WSMessageType.GRAPH_UPDATE, graph=GraphPayload())
    await connection_manager.broadcast(slug, empty)
    logger.info("rooms.reset.ok", extra={"room": slug})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
