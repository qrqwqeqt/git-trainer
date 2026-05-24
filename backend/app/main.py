"""FastAPI entrypoint: CORS, lifecycle, REST роутери, WebSocket endpoint.

Запуск у dev-режимі:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState

from app import __version__
from app.api import rooms_router, sessions_router, users_router
from app.config import Settings, get_settings
from app.db import close_db, init_db
from app.docker.sandbox import SandboxError, sandbox_manager
from app.metrics import git_metrics
from app.models.schemas import (
    HealthResponse,
    LatencyStats,
    MetricsResponse,
    SandboxMemoryResponse,
)
from app.ws.handlers import dispatch, on_user_joined, on_user_left
from app.ws.manager import connection_manager

# ----------------------------- Logging -----------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")


# ----------------------------- Lifespan ----------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown hooks.

    TODO: ініціалізувати async SQLAlchemy engine + session maker.
    """
    settings: Settings = get_settings()
    app.state.started_at = time.monotonic()
    app.state.settings = settings
    logger.info(
        "app.startup",
        extra={"version": __version__, "debug": settings.debug},
    )

    # Ініціалізуємо БД — створюємо таблиці, якщо їх ще немає.
    # Для SQLite (dev default) це створить файл; для Postgres — no-op,
    # бо там схема накатується Alembic-ом, а create_all пропустить існуючі.
    try:
        await init_db()
    except Exception:
        logger.exception("app.startup.db_init_failed")
        raise

    # Підчистити sandbox-orphan-и з попереднього запуску. Якщо daemon
    # офлайн — не фатально: ленivий start() сам обробить колізію імен,
    # коли користувач першу команду надішле.
    try:
        await sandbox_manager.cleanup_orphans()
    except SandboxError as exc:
        logger.warning(
            "app.startup.orphan_cleanup_skipped",
            extra={"reason": str(exc)},
        )

    try:
        yield
    finally:
        logger.info("app.shutdown")
        try:
            await sandbox_manager.close()
        except Exception:  # noqa: BLE001 — shutdown має бути тихим
            logger.exception("app.shutdown.sandbox_close_failed")
        try:
            await close_db()
        except Exception:  # noqa: BLE001
            logger.exception("app.shutdown.db_close_failed")


# ----------------------------- App ---------------------------------


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Git Trainer API",
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers
    app.include_router(rooms_router)
    app.include_router(users_router)
    app.include_router(sessions_router)

    # Health
    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        started_at = getattr(app.state, "started_at", None)
        uptime = max(0.0, time.monotonic() - started_at) if started_at else 0.0
        return HealthResponse(version=__version__, uptime_seconds=uptime)

    # Metrics — дешевий in-memory знімок для Розділу 4 (без Docker-викликів).
    @app.get("/metrics", response_model=MetricsResponse, tags=["meta"])
    async def metrics() -> MetricsResponse:
        started_at = getattr(app.state, "started_at", None)
        uptime = max(0.0, time.monotonic() - started_at) if started_at else 0.0
        ws_total, rooms_active = connection_manager.stats()
        snap = git_metrics.snapshot()
        settings = get_settings()
        return MetricsResponse(
            uptime_seconds=uptime,
            active_rooms=sandbox_manager.active_count(),
            max_rooms=settings.max_rooms,
            ws_connections=ws_total,
            rooms_with_connections=rooms_active,
            commands_total=git_metrics.total,
            commands_failed=git_metrics.failed,
            command_latency_ms=LatencyStats(
                count=snap.count,
                avg_ms=snap.avg_ms,
                p50_ms=snap.p50_ms,
                p95_ms=snap.p95_ms,
                p99_ms=snap.p99_ms,
                max_ms=snap.max_ms,
            ),
        )

    # Sandbox memory — окремо, бо docker stats повільний (on-demand для бенчмарку).
    @app.get(
        "/metrics/sandboxes",
        response_model=SandboxMemoryResponse,
        tags=["meta"],
    )
    async def sandbox_metrics() -> SandboxMemoryResponse:
        usage = await sandbox_manager.memory_usage()
        per_room_mib = {
            room: round(b / 1024 / 1024, 1) for room, b in usage.items()
        }
        total_mib = round(sum(usage.values()) / 1024 / 1024, 1)
        return SandboxMemoryResponse(
            count=len(usage),
            total_mib=total_mib,
            per_room_mib=per_room_mib,
        )

    # WebSocket endpoint: /ws/{room_id}?user_id=...&username=...
    @app.websocket("/ws/{room_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        room_id: str,
        user_id: str = Query(..., min_length=1),
        username: str = Query(..., min_length=1),
    ) -> None:
        await connection_manager.connect(room_id, websocket)
        db_session_id = None
        try:
            db_session_id = await on_user_joined(
                room_id, user_id, username, websocket
            )
            while True:
                raw = await websocket.receive_json()
                if not isinstance(raw, dict):
                    # Ігноруємо не-об'єкти; клієнт має слати JSON-об'єкти.
                    continue
                await dispatch(room_id, user_id, username, raw, websocket)
        except WebSocketDisconnect:
            logger.info(
                "ws.client_disconnected",
                extra={"room_id": room_id, "user_id": user_id},
            )
        except Exception:
            logger.exception(
                "ws.handler_failed",
                extra={"room_id": room_id, "user_id": user_id},
            )
            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.close(code=1011)
        finally:
            await connection_manager.disconnect(room_id, websocket)
            await on_user_left(room_id, user_id, db_session_id)

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"name": "git-trainer-backend", "version": __version__}

    # Невеликий helper для відладки 404
    @app.get("/_debug/echo/{value}", tags=["meta"], include_in_schema=False)
    async def echo(value: str) -> dict[str, str]:
        if not value:
            raise HTTPException(status_code=400, detail="value required")
        return {"echo": value}

    return app


app = create_app()
