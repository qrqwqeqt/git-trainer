"""Тести аудит-логу git-команд (repository.log_command / list_audit)."""
from __future__ import annotations

from app.db.session import get_sessionmaker
from app.db.repository import list_audit, log_command


async def test_log_and_list_audit_newest_first():
    sm = get_sessionmaker()
    async with sm() as db:
        await log_command(
            db, room_slug="r-audit", username="alice", command="git init", exit_code=0
        )
        await log_command(
            db,
            room_slug="r-audit",
            username="bob",
            command="git push origin main",
            exit_code=1,
        )
        await db.commit()

    async with sm() as db:
        rows = await list_audit(db, room_slug="r-audit")

    assert len(rows) == 2
    # новіші — першими
    assert rows[0].username == "bob"
    assert rows[0].exit_code == 1
    assert rows[1].command == "git init"


async def test_audit_is_scoped_to_room():
    sm = get_sessionmaker()
    async with sm() as db:
        await log_command(
            db, room_slug="room-a", username="u", command="git status", exit_code=0
        )
        await log_command(
            db, room_slug="room-b", username="u", command="git log", exit_code=0
        )
        await db.commit()

    async with sm() as db:
        rows_a = await list_audit(db, room_slug="room-a")

    assert len(rows_a) == 1
    assert rows_a[0].command == "git status"
