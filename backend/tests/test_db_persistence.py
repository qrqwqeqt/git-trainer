"""Тести персистенції користувачів / кімнат / сесій.

Викликаємо WS-хендлери (on_user_joined / on_user_left) напряму, без
TestClient — він використовує anyio.BlockingPortal у окремому event-loop-і,
а наш async engine cache погано переноситься між loop-ами. Direct-виклик
тестує persistence-логіку без integration-обвʼязки.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

import app.ws.handlers as handlers
from app.db.session import get_sessionmaker
from app.models.db import Room, Session as SessionRow, User
from app.ws.handlers import on_user_joined, on_user_left


@pytest.fixture(autouse=True)
def _enable_ws_db_persistence():
    """Цей модуль тестує саме persistence — вмикаємо її попри глобальний
    autouse-вимикач у conftest (ці тести не йдуть через TestClient).
    """
    prev = handlers.db_persistence_enabled
    handlers.db_persistence_enabled = True
    yield
    handlers.db_persistence_enabled = prev


async def _query_one(session_factory, stmt):
    async with session_factory() as db:
        return (await db.execute(stmt)).scalar_one_or_none()


async def _query_all(session_factory, stmt):
    async with session_factory() as db:
        return list((await db.execute(stmt)).scalars().all())


async def test_join_creates_user_room_session(fake_sandbox):
    db_session_id = await on_user_joined("r-persist", "u1", "Alice", None)
    assert db_session_id is not None

    sm = get_sessionmaker()
    user = await _query_one(sm, select(User).where(User.username == "Alice"))
    assert user is not None
    room = await _query_one(sm, select(Room).where(Room.slug == "r-persist"))
    assert room is not None
    assert room.owner_id == user.id
    sessions = await _query_all(
        sm, select(SessionRow).where(SessionRow.room_id == room.id)
    )
    assert len(sessions) == 1
    assert sessions[0].id == db_session_id
    # Поки не leave — disconnected_at не виставлений.
    assert sessions[0].disconnected_at is None


async def test_leave_marks_session_disconnected(fake_sandbox):
    db_session_id = await on_user_joined("r-leave", "u1", "Carol", None)
    await on_user_left("r-leave", "u1", db_session_id)

    sm = get_sessionmaker()
    async with sm() as db:
        row = await db.get(SessionRow, db_session_id)
    assert row is not None
    assert row.disconnected_at is not None


async def test_repeated_join_reuses_user_and_room(fake_sandbox):
    """Той самий username/slug → не дублює User/Room, додає лише Session."""
    ids = []
    for _ in range(3):
        sid = await on_user_joined("r-dup", "u1", "Bob", None)
        ids.append(sid)
        await on_user_left("r-dup", "u1", sid)

    sm = get_sessionmaker()
    users = await _query_all(sm, select(User).where(User.username == "Bob"))
    assert len(users) == 1
    rooms = await _query_all(sm, select(Room).where(Room.slug == "r-dup"))
    assert len(rooms) == 1
    sessions = await _query_all(
        sm, select(SessionRow).where(SessionRow.room_id == rooms[0].id)
    )
    assert len(sessions) == 3
    assert all(s.disconnected_at is not None for s in sessions)


async def test_two_users_same_room(fake_sandbox):
    sid_a = await on_user_joined("r-shared", "u1", "Alice", None)
    sid_b = await on_user_joined("r-shared", "u2", "Bob", None)
    await on_user_left("r-shared", "u1", sid_a)
    await on_user_left("r-shared", "u2", sid_b)

    sm = get_sessionmaker()
    rooms = await _query_all(sm, select(Room).where(Room.slug == "r-shared"))
    assert len(rooms) == 1
    sessions = await _query_all(
        sm, select(SessionRow).where(SessionRow.room_id == rooms[0].id)
    )
    assert len(sessions) == 2
    users = await _query_all(sm, select(User))
    usernames = {u.username for u in users}
    assert {"Alice", "Bob"}.issubset(usernames)


async def test_leave_without_join_is_silent(fake_sandbox):
    """on_user_left з None-ом db_session_id не повинен валитись."""
    await on_user_left("r-noop", "u1", None)


async def test_leave_with_unknown_session_id_is_silent(fake_sandbox):
    """Якщо session_id не існує — mark_session_disconnected проковтує."""
    from uuid import uuid4

    await on_user_left("r-ghost", "u1", uuid4())
