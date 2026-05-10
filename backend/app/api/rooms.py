"""REST endpoints для управління кімнатами.

Заглушки — реальна логіка з'явиться, коли під'єднаємо БД і Docker sandbox.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status

from app.models.schemas import RoomCreate, RoomRead

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


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_room(room_id: str) -> Response:
    """Видалити кімнату і зупинити sandbox. TODO."""
    logger.info("rooms.delete.stub", extra={"room_id": room_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
