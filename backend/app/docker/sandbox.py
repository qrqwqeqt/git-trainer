"""Docker sandbox: по одному контейнеру на кімнату.

Усі запущені контейнери створюються з network="none" — вони мають
ізольований Git-репозиторій і не мають доступу до мережі.

Заглушка: реальне підключення до docker daemon з'явиться, коли
ми будемо готові до інтеграційних тестів. Поки що інтерфейс фіксований,
щоб верхні шари (API / WS handlers) могли на нього покладатися.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SandboxContainer:
    """Легковаговий опис запущеного sandbox-контейнера."""

    container_id: str
    room_id: str
    image: str


class SandboxManager:
    """Створює/зупиняє sandbox-контейнери.

    TODO:
      * підключитися до docker SDK через settings.docker_socket
      * реалізувати start(room_id) / stop(room_id) / exec(room_id, argv)
      * додати метрики: скільки контейнерів активні, ліміт settings.max_rooms
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._containers: dict[str, SandboxContainer] = {}

    async def start(self, room_id: str) -> SandboxContainer:
        """Запустити новий sandbox для кімнати. Stub."""
        if len(self._containers) >= self._settings.max_rooms:
            raise RuntimeError(
                f"sandbox limit reached ({self._settings.max_rooms}); "
                f"refuse to start room {room_id}"
            )
        # TODO(docker): docker.from_env().containers.run(image, network="none", ...)
        container = SandboxContainer(
            container_id=f"stub-{room_id}",
            room_id=room_id,
            image=self._settings.sandbox_image,
        )
        self._containers[room_id] = container
        logger.info("sandbox.started.stub", extra={"room_id": room_id})
        return container

    async def stop(self, room_id: str) -> None:
        """Зупинити і видалити sandbox-контейнер. Stub."""
        container = self._containers.pop(room_id, None)
        if container is None:
            return
        # TODO(docker): container.stop(); container.remove()
        logger.info("sandbox.stopped.stub", extra={"room_id": room_id})

    async def exec(self, room_id: str, argv: list[str]) -> tuple[int, str]:
        """Виконати argv всередині sandbox. Stub.

        Повертає (exit_code, combined_output).
        """
        container = self._containers.get(room_id)
        if container is None:
            raise RuntimeError(f"no sandbox running for room {room_id}")
        # TODO(docker): container.exec_run(argv, demux=False)
        logger.info(
            "sandbox.exec.stub", extra={"room_id": room_id, "argv": argv}
        )
        return 0, "(stub output)"
