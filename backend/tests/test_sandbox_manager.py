"""Unit-тести SandboxManager з мок-докером (без реального daemon-а).

Реальний integration-тест поверх Docker буде помічений @pytest.mark.docker
і додасться у Phase 1.6 — щоб локально можна було ганяти все на CI без daemon-а.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, ImageNotFound

from app.config import Settings
from app.docker.sandbox import (
    DEFAULT_MEM_LIMIT,
    DEFAULT_PIDS_LIMIT,
    LABEL_MANAGED,
    LABEL_ROOM_ID,
    SandboxError,
    SandboxImageMissingError,
    SandboxLimitError,
    SandboxManager,
)


@pytest.fixture()
def fake_client():
    """Mock-клієнт docker.

    `containers.run` повертає завжди один і той самий mock-container — це
    спрощує перевірку викликів `.stop()` / `.remove()` у stop-тестах.
    Якщо тестам знадобиться кілька різних контейнерів — додамо реєстр.
    """
    client = MagicMock()
    client.ping.return_value = True
    client.images.get.return_value = MagicMock()
    client.close.return_value = None

    container = MagicMock()
    container.id = "cid-fake"
    client.containers.run.return_value = container
    client.containers.get.return_value = container
    return client


@pytest.fixture()
def patch_docker(monkeypatch, fake_client):
    monkeypatch.setattr(
        "app.docker.sandbox.docker.from_env", lambda: fake_client
    )
    return fake_client


@pytest.fixture()
def settings():
    return Settings(
        max_rooms=2,
        sandbox_image="git-trainer-sandbox:test",
    )


async def test_start_creates_container_with_security_flags(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    sandbox = await mgr.start("room-1")

    assert sandbox.room_id == "room-1"
    assert sandbox.name == "git-trainer-room-1"
    assert sandbox.container_id == "cid-fake"

    patch_docker.containers.run.assert_called_once()
    args, kwargs = patch_docker.containers.run.call_args
    assert args[0] == "git-trainer-sandbox:test"
    assert kwargs["detach"] is True
    assert kwargs["network_mode"] == "none"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["mem_limit"] == DEFAULT_MEM_LIMIT
    assert kwargs["pids_limit"] == DEFAULT_PIDS_LIMIT
    assert kwargs["labels"][LABEL_MANAGED] == "true"
    assert kwargs["labels"][LABEL_ROOM_ID] == "room-1"


async def test_start_idempotent_per_room(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    s1 = await mgr.start("room-1")
    s2 = await mgr.start("room-1")
    assert s1 is s2
    assert patch_docker.containers.run.call_count == 1


async def test_start_respects_max_rooms(patch_docker, settings):
    mgr = SandboxManager(settings=settings)  # max_rooms=2
    await mgr.start("a")
    await mgr.start("b")
    with pytest.raises(SandboxLimitError):
        await mgr.start("c")
    assert mgr.active_count() == 2


async def test_start_image_missing_translates_error(patch_docker, settings):
    patch_docker.containers.run.side_effect = ImageNotFound("nope")
    mgr = SandboxManager(settings=settings)
    with pytest.raises(SandboxImageMissingError):
        await mgr.start("r1")


async def test_start_api_error_wrapped(patch_docker, settings):
    patch_docker.containers.run.side_effect = APIError("name conflict")
    mgr = SandboxManager(settings=settings)
    with pytest.raises(SandboxError):
        await mgr.start("r1")


async def test_stop_calls_docker_and_frees_slot(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    sandbox = await mgr.start("r1")
    await mgr.stop("r1")
    assert mgr.active_count() == 0

    patch_docker.containers.get.assert_called_with(sandbox.container_id)
    container = patch_docker.containers.get.return_value
    container.stop.assert_called_once()
    container.remove.assert_called_once()

    # Слот звільнився — можна стартувати інший
    await mgr.start("r2")


async def test_stop_idempotent_when_unknown_room(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.stop("never-started")
    patch_docker.containers.get.assert_not_called()


async def test_verify_image_missing_raises(patch_docker, settings):
    patch_docker.images.get.side_effect = ImageNotFound("nope")
    mgr = SandboxManager(settings=settings)
    with pytest.raises(SandboxImageMissingError):
        await mgr.verify()


async def test_verify_ok(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.verify()
    patch_docker.ping.assert_called_once()
    patch_docker.images.get.assert_called_once_with("git-trainer-sandbox:test")
