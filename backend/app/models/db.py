"""SQLAlchemy 2.0 async ORM models.

Типи обрані так, щоб модель компілювалась і в Postgres, і в SQLite:
  * `Uuid` (generic) — мапиться в native UUID у Postgres, у CHAR(32) у SQLite.
  * `DateTime(timezone=True)` — Postgres зберігає tz, SQLite — UTC у TEXT.
  * `func.now()` server_default — обидва діалекти підтримують.

У dev/test за замовчуванням використовується SQLite через aiosqlite
(див. `config.DATABASE_URL`). У проді — Postgres через asyncpg, без
змін у моделях.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base для всіх моделей."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rooms: Mapped[list["Room"]] = relationship(back_populates="owner")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # `slug` — публічний рядковий ідентифікатор з URL (`/ws/{slug}`). Доменна
    # модель — uuid `id`; slug — для людського посилання та для lookup-у з WS.
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    sandbox_container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="rooms")
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class Session(Base):
    """Підключення одного студента до кімнати через WebSocket."""

    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    room: Mapped[Room] = relationship(back_populates="sessions")
    user: Mapped[User] = relationship(back_populates="sessions")
