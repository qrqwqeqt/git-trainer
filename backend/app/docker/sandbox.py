"""Docker sandbox: по одному контейнеру на кімнату.

Усі контейнери стартують з network="none", cap_drop=ALL, no-new-privileges
та лімітами пам'яті/процесів. docker SDK синхронний, тому всі виклики йдуть
через `asyncio.to_thread`, щоб не блокувати event-loop FastAPI.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound

from app.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover
    from docker.models.containers import Container

logger = logging.getLogger(__name__)


# Ярлики контейнерів — щоб після рестарту бекенду знаходити orphan-и.
LABEL_MANAGED = "git-trainer.managed"
LABEL_ROOM_ID = "git-trainer.room_id"

# Резонні ліміти для навчального sandbox-у.
DEFAULT_MEM_LIMIT = "256m"
DEFAULT_PIDS_LIMIT = 128
STOP_TIMEOUT_SECONDS = 5


class SandboxError(Exception):
    """Базова помилка SandboxManager."""


class SandboxLimitError(SandboxError):
    """Кількість активних sandbox-ів досягла max_rooms."""


class SandboxImageMissingError(SandboxError):
    """Image для sandbox не знайдено локально (треба зробити docker build)."""


@dataclass(slots=True)
class SandboxContainer:
    """Легкий запис про запущений sandbox-контейнер."""

    container_id: str
    room_id: str
    image: str
    name: str


class SandboxManager:
    """Створює/зупиняє sandbox-контейнери (1 на кімнату)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._containers: dict[str, SandboxContainer] = {}
        self._client: docker.DockerClient | None = None
        # Глобальний lock на start/stop. Для max_rooms=50 це не вузьке місце;
        # якщо стане — замінимо на per-room locking.
        self._lock = asyncio.Lock()

    # ------------------------------ Lifecycle ------------------------------

    async def _client_or_connect(self) -> docker.DockerClient:
        """Лінива ініціалізація docker клієнта (синхронний → to_thread)."""
        if self._client is not None:
            return self._client
        try:
            client = await asyncio.to_thread(docker.from_env)
            await asyncio.to_thread(client.ping)
        except DockerException as exc:
            raise SandboxError(f"docker daemon unreachable: {exc}") from exc
        self._client = client
        return client

    async def verify(self) -> None:
        """Зовнішні залежності: daemon + image. Кликати з lifespan startup."""
        client = await self._client_or_connect()
        try:
            await asyncio.to_thread(client.images.get, self._settings.sandbox_image)
        except ImageNotFound as exc:
            raise SandboxImageMissingError(
                f"sandbox image {self._settings.sandbox_image!r} not found; "
                "run: docker build -t git-trainer-sandbox:latest docker/sandbox"
            ) from exc

    async def close(self) -> None:
        """Закрити docker клієнт. Кликати з lifespan shutdown."""
        if self._client is None:
            return
        try:
            await asyncio.to_thread(self._client.close)
        finally:
            self._client = None

    # ------------------------------ start/stop -----------------------------

    async def start(self, room_id: str) -> SandboxContainer:
        """Запустити sandbox для кімнати або повернути існуючий."""
        async with self._lock:
            existing = self._containers.get(room_id)
            if existing is not None:
                return existing
            if len(self._containers) >= self._settings.max_rooms:
                raise SandboxLimitError(
                    f"sandbox limit reached ({self._settings.max_rooms})"
                )

            client = await self._client_or_connect()
            name = f"git-trainer-{room_id}"
            try:
                container: Container = await asyncio.to_thread(
                    client.containers.run,
                    self._settings.sandbox_image,
                    detach=True,
                    name=name,
                    # ---- мережна та системна ізоляція ----
                    network_mode="none",
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    # ---- ресурсні ліміти ----
                    mem_limit=DEFAULT_MEM_LIMIT,
                    pids_limit=DEFAULT_PIDS_LIMIT,
                    # ---- ярлики для cleanup orphans ----
                    labels={LABEL_MANAGED: "true", LABEL_ROOM_ID: room_id},
                )
            except ImageNotFound as exc:
                raise SandboxImageMissingError(
                    f"sandbox image {self._settings.sandbox_image!r} not found"
                ) from exc
            except APIError as exc:
                raise SandboxError(
                    f"failed to start sandbox for {room_id}: {exc}"
                ) from exc

            sandbox = SandboxContainer(
                container_id=container.id,
                room_id=room_id,
                image=self._settings.sandbox_image,
                name=name,
            )
            self._containers[room_id] = sandbox

        logger.info(
            "sandbox.started",
            extra={
                "room_id": room_id,
                "container_id": sandbox.container_id,
                "container_name": name,
            },
        )
        return sandbox

    async def stop(self, room_id: str) -> None:
        """Зупинити та видалити sandbox-контейнер. Idempotent."""
        async with self._lock:
            sandbox = self._containers.pop(room_id, None)
            if sandbox is None:
                return
            client = await self._client_or_connect()
            try:
                container = await asyncio.to_thread(
                    client.containers.get, sandbox.container_id
                )
            except NotFound:
                logger.warning(
                    "sandbox.stop.container_missing",
                    extra={
                        "room_id": room_id,
                        "container_id": sandbox.container_id,
                    },
                )
                return

            try:
                await asyncio.to_thread(container.stop, timeout=STOP_TIMEOUT_SECONDS)
            except (APIError, NotFound):
                logger.warning(
                    "sandbox.stop.stop_failed",
                    extra={"room_id": room_id},
                    exc_info=True,
                )

            try:
                await asyncio.to_thread(container.remove, force=True)
            except NotFound:
                pass
            except APIError:
                logger.warning(
                    "sandbox.stop.remove_failed",
                    extra={"room_id": room_id},
                    exc_info=True,
                )
                return

        logger.info(
            "sandbox.stopped",
            extra={
                "room_id": room_id,
                "container_id": sandbox.container_id,
            },
        )

    # -------------------------------- exec --------------------------------

    async def exec(self, room_id: str, argv: list[str]) -> tuple[int, str]:
        """Виконати argv всередині sandbox.

        TODO(phase-1.3): client.containers.get(id).exec_run(argv, demux=True),
        повертати реальний (exit_code, combined_output).
        """
        async with self._lock:
            sandbox = self._containers.get(room_id)
        if sandbox is None:
            raise SandboxError(f"no sandbox running for room {room_id}")
        logger.info(
            "sandbox.exec.stub", extra={"room_id": room_id, "argv": argv}
        )
        return 0, "(stub output)"

    # ---------------------------- Introspection ---------------------------

    def active_count(self) -> int:
        return len(self._containers)

    def get(self, room_id: str) -> SandboxContainer | None:
        return self._containers.get(room_id)
