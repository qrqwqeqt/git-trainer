"""Unit-тести SandboxManager з мок-докером (без реального daemon-а).

Реальний integration-тест поверх Docker буде помічений @pytest.mark.docker
і додасться у Phase 1.6 — щоб локально можна було ганяти все на CI без daemon-а.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, ImageNotFound

from app.config import Settings
from app.docker.sandbox import (
    DEFAULT_MEM_LIMIT,
    DEFAULT_PIDS_LIMIT,
    LABEL_MANAGED,
    LABEL_ROOM_ID,
    ExecResult,
    SandboxError,
    SandboxImageMissingError,
    SandboxLimitError,
    SandboxManager,
    SandboxTimeoutError,
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
    # Generic API error (без «already in use») — wrap у SandboxError.
    patch_docker.containers.run.side_effect = APIError("internal server error")
    mgr = SandboxManager(settings=settings)
    with pytest.raises(SandboxError):
        await mgr.start("r1")


async def test_start_name_conflict_adopts_and_retries(patch_docker, settings):
    """Якщо container з таким іменем уже є (orphan) — видалити й створити заново."""
    conflict = APIError(
        "Conflict. The container name \"/git-trainer-r1\" is already in use"
    )
    success_container = patch_docker.containers.run.return_value
    patch_docker.containers.run.side_effect = [conflict, success_container]

    mgr = SandboxManager(settings=settings)
    sandbox = await mgr.start("r1")

    assert sandbox.room_id == "r1"
    # Старий контейнер дістали через containers.get і викинули.
    patch_docker.containers.get.assert_called_with("git-trainer-r1")
    orphan = patch_docker.containers.get.return_value
    orphan.remove.assert_called_once_with(force=True)
    # run викликався двічі — спершу conflict, потім успіх.
    assert patch_docker.containers.run.call_count == 2


async def test_cleanup_orphans_removes_labeled_containers(patch_docker, settings):
    c1 = MagicMock()
    c1.id = "abc1"
    c2 = MagicMock()
    c2.id = "abc2"
    patch_docker.containers.list.return_value = [c1, c2]

    mgr = SandboxManager(settings=settings)
    removed = await mgr.cleanup_orphans()

    assert removed == 2
    patch_docker.containers.list.assert_called_once_with(
        all=True,
        filters={"label": "git-trainer.managed=true"},
    )
    c1.remove.assert_called_once_with(force=True)
    c2.remove.assert_called_once_with(force=True)


async def test_cleanup_orphans_returns_zero_when_none(patch_docker, settings):
    patch_docker.containers.list.return_value = []
    mgr = SandboxManager(settings=settings)
    assert await mgr.cleanup_orphans() == 0


async def test_cleanup_orphans_swallows_per_container_failures(patch_docker, settings):
    """Помилка видалення одного контейнера не повинна валити cleanup усіх."""
    from docker.errors import APIError as _APIError

    c_ok = MagicMock()
    c_ok.id = "ok"
    c_fail = MagicMock()
    c_fail.id = "fail"
    c_fail.remove.side_effect = _APIError("daemon angry")
    patch_docker.containers.list.return_value = [c_ok, c_fail]

    mgr = SandboxManager(settings=settings)
    removed = await mgr.cleanup_orphans()
    # Один успішно видалили, інший залишився — не падаємо.
    assert removed == 1


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


# --------------------------------- exec ---------------------------------


async def test_exec_returns_decoded_output(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.start("r1")
    container = patch_docker.containers.get.return_value
    container.exec_run.return_value = (0, (b"on branch main\n", b""))

    result = await mgr.exec("r1", ["git", "status"])

    assert isinstance(result, ExecResult)
    assert result.exit_code == 0
    assert result.stdout == "on branch main\n"
    assert result.stderr == ""
    container.exec_run.assert_called_once_with(["git", "status"], demux=True)


async def test_exec_handles_none_streams(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.start("r1")
    container = patch_docker.containers.get.return_value
    container.exec_run.return_value = (0, (None, None))

    result = await mgr.exec("r1", ["git", "status"])
    assert result.stdout == ""
    assert result.stderr == ""


async def test_exec_handles_none_output(patch_docker, settings):
    """Деякі версії docker SDK можуть віддати output=None для порожнього виводу."""
    mgr = SandboxManager(settings=settings)
    await mgr.start("r1")
    container = patch_docker.containers.get.return_value
    container.exec_run.return_value = (0, None)

    result = await mgr.exec("r1", ["true"])
    assert result.stdout == ""
    assert result.stderr == ""


async def test_exec_propagates_nonzero_exit(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.start("r1")
    container = patch_docker.containers.get.return_value
    container.exec_run.return_value = (
        128,
        (b"", b"fatal: not a git repository\n"),
    )

    result = await mgr.exec("r1", ["git", "log"])
    assert result.exit_code == 128
    assert result.stderr == "fatal: not a git repository\n"


async def test_exec_room_unknown_raises(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    with pytest.raises(SandboxError):
        await mgr.exec("ghost", ["git", "status"])


async def test_exec_decodes_invalid_utf8_with_replace(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.start("r1")
    container = patch_docker.containers.get.return_value
    container.exec_run.return_value = (0, (b"\xff\xfeok\n", b""))

    result = await mgr.exec("r1", ["true"])
    # «зіпсовані» байти замінюються на U+FFFD, а не падаємо UnicodeDecodeError
    assert "ok" in result.stdout
    assert "�" in result.stdout


async def test_exec_timeout_raises(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.start("r1")
    container = patch_docker.containers.get.return_value

    release = threading.Event()

    def _slow(*_args, **_kwargs):
        release.wait(timeout=2.0)
        return (0, (b"", b""))

    container.exec_run.side_effect = _slow

    try:
        with pytest.raises(SandboxTimeoutError):
            await mgr.exec("r1", ["sleep", "100"], timeout=0.05)
    finally:
        # Відпускаємо thread, щоб не висів після тесту.
        release.set()


async def test_exec_api_error_wrapped(patch_docker, settings):
    mgr = SandboxManager(settings=settings)
    await mgr.start("r1")
    container = patch_docker.containers.get.return_value
    container.exec_run.side_effect = APIError("daemon angry")

    with pytest.raises(SandboxError):
        await mgr.exec("r1", ["git", "status"])
