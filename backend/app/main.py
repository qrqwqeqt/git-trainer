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
from app.models.schemas import HealthResponse
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

    TODO: ініціалізувати async SQLAlchemy engine + session maker, перевірити
    доступність docker daemon, прогріти sandbox image.
    """
    settings: Settings = get_settings()
    app.state.started_at = time.monotonic()
    app.state.settings = settings
    logger.info(
        "app.startup",
        extra={"version": __version__, "debug": settings.debug},
    )
    try:
        yield
    finally:
        logger.info("app.shutdown")


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

    # WebSocket endpoint: /ws/{room_id}?user_id=...&username=...
    @app.websocket("/ws/{room_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        room_id: str,
        user_id: str = Query(..., min_length=1),
        username: str = Query(..., min_length=1),
    ) -> None:
        await connection_manager.connect(room_id, websocket)
        try:
            await on_user_joined(room_id, user_id, username)
            while True:
                raw = await websocket.receive_json()
                if not isinstance(raw, dict):
                    # Ігноруємо не-об'єкти; клієнт має слати JSON-об'єкти.
                    continue
                await dispatch(room_id, user_id, raw, websocket)
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
            await on_user_left(room_id, user_id)

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
