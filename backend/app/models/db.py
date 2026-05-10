"""SQLAlchemy 2.0 async ORM models.

Заглушковий шар: реальні міграції створимо через Alembic, коли будемо
підключати БД. Поки що моделі описують контракт таблиць.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base для всіх моделей."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rooms: Mapped[list["Room"]] = relationship(back_populates="owner")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
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

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    room: Mapped[Room] = relationship(back_populates="sessions")
    user: Mapped[User] = relationship(back_populates="sessions")
