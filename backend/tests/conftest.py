"""Pytest налаштування: asyncio mode + імпорт FastAPI app."""
from __future__ import annotations

import pytest

from app.main import app as fastapi_app


@pytest.fixture()
def app():
    return fastapi_app
