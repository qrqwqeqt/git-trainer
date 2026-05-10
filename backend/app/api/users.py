"""REST endpoints для користувачів (заглушки)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import UserCreate, UserRead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate) -> UserRead:
    """Зареєструвати нового користувача. TODO: зберігання в БД."""
    logger.info("users.create.stub", extra={"username": payload.username})
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="create_user not implemented yet",
    )


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: str) -> UserRead:
    """Отримати профіль користувача. TODO."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"user {user_id} not found (stub)",
    )
