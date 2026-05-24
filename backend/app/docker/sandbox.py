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
EXEC_TIMEOUT_SECONDS = 10.0


class SandboxError(Exception):
    """Базова помилка SandboxManager."""


class SandboxLimitError(SandboxError):
    """Кількість активних sandbox-ів досягла max_rooms."""


class SandboxImageMissingError(SandboxError):
    """Image для sandbox не знайдено локально (треба зробити docker build)."""


class SandboxTimeoutError(SandboxError):
    """Виконання команди в sandbox-і перевищило встановлений тайм-аут."""


def _is_name_conflict(exc: APIError) -> bool:
    """docker daemon відповідає 409 з підстрокою «already in use» при колізії
    імені контейнера. У docker-py статус-код доступний як `exc.status_code`,
    але це обʼєкт може бути None — тому ще і дивимось у текст помилки.
    """
    status = getattr(exc, "status_code", None)
    if status == 409:
        return True
    return "already in use" in str(exc).lower()


@dataclass(slots=True)
class SandboxContainer:
    """Легкий запис про запущений sandbox-контейнер."""

    container_id: str
    room_id: str
    image: str
    name: str


@dataclass(slots=True)
class ExecResult:
    """Результат виконання argv усередині sandbox-контейнера."""

    exit_code: int
    stdout: str
    stderr: str


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

    async def cleanup_orphans(self) -> int:
        """Видалити sandbox-контейнери, лишені від попереднього запуску backend-а.

        Кликати з lifespan startup. Знаходимо контейнери за ярликом
        LABEL_MANAGED, не зважаючи на стан (running/stopped/dead). Повертає
        кількість видалених. Якщо daemon недоступний — кидає SandboxError,
        викликач сам вирішує, фатально це чи warning.
        """
        client = await self._client_or_connect()
        try:
            containers = await asyncio.to_thread(
                client.containers.list,
                all=True,
                filters={"label": f"{LABEL_MANAGED}=true"},
            )
        except DockerException as exc:
            raise SandboxError(f"failed to list orphan containers: {exc}") from exc

        removed = 0
        for c in containers:
            try:
                await asyncio.to_thread(c.remove, force=True)
                removed += 1
            except NotFound:
                pass
            except APIError:
                logger.warning(
                    "sandbox.cleanup.remove_failed",
                    extra={"container_id": c.id},
                    exc_info=True,
                )
        if removed:
            logger.info("sandbox.cleanup.done", extra={"removed": removed})
        return removed

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
            run_kwargs = {
                "detach": True,
                "name": name,
                # ---- мережна та системна ізоляція ----
                "network_mode": "none",
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                # ---- ресурсні ліміти ----
                "mem_limit": DEFAULT_MEM_LIMIT,
                "pids_limit": DEFAULT_PIDS_LIMIT,
                # ---- ярлики для cleanup orphans ----
                "labels": {LABEL_MANAGED: "true", LABEL_ROOM_ID: room_id},
            }
            try:
                container: Container = await asyncio.to_thread(
                    client.containers.run,
                    self._settings.sandbox_image,
                    **run_kwargs,
                )
            except ImageNotFound as exc:
                raise SandboxImageMissingError(
                    f"sandbox image {self._settings.sandbox_image!r} not found"
                ) from exc
            except APIError as exc:
                # Name conflict — orphan від попереднього запуску backend-а,
                # який не потрапив у cleanup_orphans (наприклад, daemon був
                # offline при старті). Видаляємо та робимо одну повторну спробу.
                if _is_name_conflict(exc):
                    logger.warning(
                        "sandbox.start.name_conflict.adopting",
                        extra={"container_name": name, "room_id": room_id},
                    )
                    try:
                        old = await asyncio.to_thread(client.containers.get, name)
                        await asyncio.to_thread(old.remove, force=True)
                    except NotFound:
                        pass
                    except APIError as remove_exc:
                        raise SandboxError(
                            f"failed to remove orphan {name}: {remove_exc}"
                        ) from remove_exc
                    try:
                        container = await asyncio.to_thread(
                            client.containers.run,
                            self._settings.sandbox_image,
                            **run_kwargs,
                        )
                    except APIError as retry_exc:
                        raise SandboxError(
                            f"failed to start sandbox for {room_id} after "
                            f"orphan cleanup: {retry_exc}"
                        ) from retry_exc
                else:
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

    async def exec(
        self,
        room_id: str,
        argv: list[str],
        *,
        timeout: float = EXEC_TIMEOUT_SECONDS,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Виконати argv всередині sandbox-контейнера.

        Повертає ExecResult з exit_code та декодованими stdout/stderr
        (UTF-8, errors=replace для безпеки).

        `env` — додаткові змінні оточення для exec (напр. GIT_AUTHOR_NAME під
        конкретного студента). Передаються напряму у docker exec; shell не
        задіяний (argv — список), тож ризику ін'єкції немає.

        NOTE про тайм-аут: реалізовано через `asyncio.wait_for`. Якщо тайм-аут
        спрацьовує, сама команда у контейнері продовжує виконуватись — docker
        SDK не має API для скасування exec. Захист від ескалації — через
        pids_limit / mem_limit / network=none / cap_drop, заданих у start().
        """
        async with self._lock:
            sandbox = self._containers.get(room_id)
        if sandbox is None:
            raise SandboxError(f"no sandbox running for room {room_id}")

        client = await self._client_or_connect()
        try:
            container = await asyncio.to_thread(
                client.containers.get, sandbox.container_id
            )
        except NotFound as exc:
            raise SandboxError(
                f"sandbox container missing for room {room_id}"
            ) from exc

        try:
            exit_code, output = await asyncio.wait_for(
                asyncio.to_thread(
                    container.exec_run, argv, demux=True, environment=env
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.warning(
                "sandbox.exec.timeout",
                extra={
                    "room_id": room_id,
                    "argv": argv,
                    "timeout_s": timeout,
                },
            )
            raise SandboxTimeoutError(
                f"sandbox exec timed out after {timeout}s"
            ) from exc
        except APIError as exc:
            raise SandboxError(f"sandbox exec failed: {exc}") from exc

        # demux=True → output це (stdout_bytes, stderr_bytes); кожна з них
        # може бути None, якщо відповідний потік порожній.
        if output is None:
            stdout_bytes, stderr_bytes = None, None
        else:
            stdout_bytes, stderr_bytes = output
        stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")

        logger.info(
            "sandbox.exec",
            extra={
                "room_id": room_id,
                "argv": argv,
                "exit_code": exit_code,
            },
        )
        return ExecResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    # ---------------------------- Introspection ---------------------------

    def active_count(self) -> int:
        return len(self._containers)

    def get(self, room_id: str) -> SandboxContainer | None:
        return self._containers.get(room_id)

    async def memory_usage(self) -> dict[str, int]:
        """Поточне споживання памʼяті активними sandbox-ами (байти).

        Через `docker stats` (stream=False) — повільно, бо daemon сэмплює
        ~1 c на контейнер. Тому лише для on-demand метрик / бенчмарку, НЕ
        для гарячого шляху. Контейнери, що зникли, тихо пропускаємо.
        """
        async with self._lock:
            items = list(self._containers.items())
        if not items:
            return {}
        client = await self._client_or_connect()
        usage: dict[str, int] = {}
        for room_id, sb in items:
            try:
                container = await asyncio.to_thread(
                    client.containers.get, sb.container_id
                )
                stats = await asyncio.to_thread(container.stats, stream=False)
            except (NotFound, APIError, DockerException):
                continue
            mem = stats.get("memory_stats", {}).get("usage")
            if isinstance(mem, int):
                usage[room_id] = mem
        return usage


# Модуль-рівневий singleton — імпортуємо у хендлерах і lifespan.
# docker-клієнт ініціалізується ліниво в _client_or_connect, тому
# створення цього об'єкта саме по собі дешеве й безпечне для тестів.
sandbox_manager = SandboxManager()
