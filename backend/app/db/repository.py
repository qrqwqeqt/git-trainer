"""CRUD-хелпери поверх AsyncSession.

Тут зосереджена вся ORM-логіка для WS-хендлерів: get-or-create users і
rooms, реєстрація та закриття Session-рядків. Endpoint-и (Phase 2.3+)
використовуватимуть ті ж функції.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Room, Session as SessionRow, User


async def get_or_create_user(session: AsyncSession, username: str) -> User:
    """Знайти користувача за username або створити нового."""
    stmt = select(User).where(User.username == username)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is not None:
        return user
    user = User(username=username)
    session.add(user)
    await session.flush()  # отримати user.id без виходу з транзакції
    return user


async def get_or_create_room(
    session: AsyncSession,
    *,
    slug: str,
    owner_id: UUID,
    display_name: str | None = None,
) -> Room:
    """Знайти кімнату за slug-ом або створити нову з owner-ом за замовчуванням.

    display_name за умовчанням збігається зі slug-ом; його можна змінити пізніше
    через CRUD endpoint (Phase 2.4).
    """
    stmt = select(Room).where(Room.slug == slug)
    room = (await session.execute(stmt)).scalar_one_or_none()
    if room is not None:
        return room
    room = Room(slug=slug, name=display_name or slug, owner_id=owner_id)
    session.add(room)
    await session.flush()
    return room


async def create_session_row(
    session: AsyncSession,
    *,
    room_id: UUID,
    user_id: UUID,
) -> SessionRow:
    """Створити рядок Session при підключенні WebSocket-а."""
    row = SessionRow(room_id=room_id, user_id=user_id)
    session.add(row)
    await session.flush()
    return row


async def mark_session_disconnected(
    session: AsyncSession,
    session_id: UUID,
) -> None:
    """Поставити disconnected_at=now() при закритті WebSocket-а.

    Якщо рядок уже закритий (повторний disconnect) або не знайдено — тихо
    пропускаємо, ця операція повинна бути ідемпотентною.
    """
    row = await session.get(SessionRow, session_id)
    if row is None or row.disconnected_at is not None:
        return
    row.disconnected_at = datetime.now(timezone.utc)
