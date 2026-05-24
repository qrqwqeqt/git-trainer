"""Pydantic схеми: WebSocket-протокол та REST DTO.

Відповідає контракту з CLAUDE.md:
    { "type": "GIT_EVENT", "action": "commit", "payload": { ... } }
    { "type": "USER_JOINED", "userId": "...", "username": "..." }
    { "type": "GRAPH_UPDATE", "graph": { "nodes": [...], "edges": [...] } }
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID


class StrEnum(str, Enum):
    """str-Enum для сумісності з Python <3.11.

    На 3.11+ можна замінити на `enum.StrEnum` без зміни поведінки.
    """

    def __str__(self) -> str:  # pragma: no cover — trivial
        return str(self.value)

from pydantic import BaseModel, ConfigDict, Field


# ----------------------------- WebSocket protocol -----------------------------


class WSMessageType(StrEnum):
    """Типи WS-повідомлень, якими обмінюються клієнт і сервер."""

    GIT_EVENT = "GIT_EVENT"
    USER_JOINED = "USER_JOINED"
    USER_LEFT = "USER_LEFT"
    GRAPH_UPDATE = "GRAPH_UPDATE"
    GIT_COMMAND = "GIT_COMMAND"  # client → server
    ERROR = "ERROR"


class GitEventPayload(BaseModel):
    """Дані, які супроводжують будь-яку Git-подію."""

    model_config = ConfigDict(extra="allow")

    hash: str | None = None
    message: str | None = None
    branch: str | None = None
    parents: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str | None = None
    branch: str | None = None
    parents: list[str] = Field(default_factory=list)
    author: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str


class GraphPayload(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class WSMessage(BaseModel):
    """Універсальний контейнер для будь-якого WS-повідомлення.

    Конкретна форма визначається полем `type`; `payload` / `graph` заповнюються
    залежно від події.
    """

    type: WSMessageType
    action: str | None = None
    userId: str | None = None
    username: str | None = None
    payload: dict[str, Any] | None = None
    graph: GraphPayload | None = None
    ts: datetime = Field(default_factory=datetime.utcnow)


# --------------------------------- REST DTO -----------------------------------


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)


class UserRead(BaseModel):
    id: UUID
    username: str
    created_at: datetime


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    owner_id: UUID


class RoomRead(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    sandbox_container_id: str | None = None
    created_at: datetime


class SessionRead(BaseModel):
    id: UUID
    room_id: UUID
    user_id: UUID
    connected_at: datetime
    disconnected_at: datetime | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    uptime_seconds: float


class LatencyStats(BaseModel):
    """Статистика латентності git-команд (мс) для Розділу 4."""

    count: int
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


class MetricsResponse(BaseModel):
    """Знімок метрик процесу: кімнати, з'єднання, латентність команд."""

    uptime_seconds: float
    active_rooms: int
    max_rooms: int
    ws_connections: int
    rooms_with_connections: int
    commands_total: int
    commands_failed: int
    command_latency_ms: LatencyStats


class SandboxMemoryResponse(BaseModel):
    """Споживання памʼяті активними sandbox-контейнерами (on-demand)."""

    count: int
    total_mib: float
    per_room_mib: dict[str, float]
