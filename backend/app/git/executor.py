"""Виконавець Git-команд.

SECURITY (див. CLAUDE.md → Security Rules):
  * Git-команди виконуються ТІЛЬКИ всередині Docker sandbox-контейнера.
  * Перед передачею в контейнер команда проходить через whitelist.
  * Сирі shell-команди на хості — заборонені.

Тут — лише заглушка з валідацією. Фактичне виконання делегуватиметься
`app.docker.sandbox.SandboxManager.exec(...)` у майбутньому.
"""
from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass

from app.models.schemas import GitEventPayload

logger = logging.getLogger(__name__)

# Whitelist Git-підкоманд, які дозволені студентам. Все інше — відхиляємо.
ALLOWED_GIT_COMMANDS: frozenset[str] = frozenset(
    {
        "init",
        "status",
        "add",
        "commit",
        "log",
        "branch",
        "checkout",
        "switch",
        "merge",
        "rebase",
        "reset",
        "diff",
        "show",
        "tag",
        "stash",
        "restore",
    }
)


class GitCommandError(Exception):
    """Підняти, коли команда не пройшла валідацію або впала у sandbox."""


@dataclass(slots=True)
class GitCommandExecutor:
    """Валідує та (в майбутньому) виконує Git-команди в sandbox-контейнері."""

    room_id: str
    container_id: str | None = None

    def _validate(self, command: str) -> list[str]:
        """Розібрати команду і перевірити whitelist.

        Повертає розбитий argv. Кидає GitCommandError при порушеннях.
        """
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise GitCommandError(f"invalid shell syntax: {exc}") from exc
        if not argv or argv[0] != "git":
            raise GitCommandError("only `git ...` commands are allowed")
        if len(argv) < 2:
            raise GitCommandError("missing git subcommand")
        subcommand = argv[1]
        if subcommand not in ALLOWED_GIT_COMMANDS:
            raise GitCommandError(f"git subcommand `{subcommand}` is not whitelisted")
        # Додатково: заборонити shell-метасимволи (; && || | > < ` $)
        for forbidden in (";", "&&", "||", "|", ">", "<", "`", "$("):
            if forbidden in command:
                raise GitCommandError(f"forbidden token in command: {forbidden!r}")
        return argv

    async def run(self, command: str) -> GitEventPayload:
        """Виконати Git-команду всередині sandbox-контейнера.

        TODO: інтегрувати з SandboxManager і парсити stdout у GitEventPayload.
        Поки що — повертає «сухий» payload, не торкаючись диска/Docker.
        """
        argv = self._validate(command)
        logger.info(
            "git.exec.stub",
            extra={"room_id": self.room_id, "argv": argv, "container": self.container_id},
        )
        # TODO(sandbox): SandboxManager(self.container_id).exec(argv)
        return GitEventPayload(message=f"(stub) would run: {' '.join(argv)}")
