"""Виконавець Git-команд.

SECURITY (див. CLAUDE.md → Security Rules):
  * Git-команди виконуються ТІЛЬКИ всередині Docker sandbox-контейнера.
  * Перед передачею в контейнер команда проходить через whitelist.
  * Сирі shell-команди на хості — заборонені.

Workflow:
  1. validate(command) — whitelist + блокування shell-метасимволів.
  2. SandboxManager.exec(room_id, argv) — реальне виконання у контейнері.
  3. Якщо команда write-ова та exit_code=0 — ще раз exec з LOG_ARGV
     для отримання актуального графа, потім parse_graph().
"""
from __future__ import annotations

import logging
import re
import shlex
import time
from dataclasses import dataclass, field

from app.docker.sandbox import SandboxManager
from app.git.parser import LOG_ARGV, parse_graph
from app.metrics import git_metrics
from app.models.schemas import GraphPayload

logger = logging.getLogger(__name__)

# Whitelist Git-підкоманд, дозволених студентам. Усе інше — відхиляємо.
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

# Команди, які НЕ змінюють refs/коміти — для них пропускаємо graph refresh.
READONLY_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {"status", "log", "diff", "show"}
)

# Заборонені shell-метасимволи (захист від обходу whitelist).
_FORBIDDEN_TOKENS: tuple[str, ...] = (";", "&&", "||", "|", ">", "<", "`", "$(")


def _email_slug(name: str) -> str:
    """Згенерувати латинський slug для синтетичного email автора."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "student"


class GitCommandError(Exception):
    """Команда не пройшла валідацію або впала у sandbox."""


@dataclass(slots=True)
class ExecOutcome:
    """Результат виконання git-команди: подія + (опційно) свіжий граф."""

    action: str
    exit_code: int
    stdout: str
    stderr: str
    argv: list[str] = field(default_factory=list)
    graph: GraphPayload | None = None


class GitCommandExecutor:
    """Валідує та виконує Git-команди у sandbox-контейнері кімнати."""

    def __init__(
        self,
        room_id: str,
        sandbox: SandboxManager,
        *,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> None:
        self.room_id = room_id
        self.sandbox = sandbox
        # Git-env, щоб коміт підписувався реальним студентом, а не глобальним
        # "Student" з образу. Завдяки цьому ховер у графі показує справжнього
        # автора (ключова частина multi-user-задуму).
        self._env = self._build_author_env(author_name, author_email)

    @staticmethod
    def _build_author_env(
        author_name: str | None, author_email: str | None
    ) -> dict[str, str] | None:
        if not author_name:
            return None
        email = author_email or f"{_email_slug(author_name)}@git-trainer.local"
        return {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": email,
        }

    def _validate(self, command: str) -> list[str]:
        """Розібрати команду і перевірити whitelist. Кидає GitCommandError."""
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
            raise GitCommandError(
                f"git subcommand `{subcommand}` is not whitelisted"
            )
        for forbidden in _FORBIDDEN_TOKENS:
            if forbidden in command:
                raise GitCommandError(
                    f"forbidden token in command: {forbidden!r}"
                )
        return argv

    async def run(self, command: str) -> ExecOutcome:
        """Виконати команду; для write-команд оновити та повернути граф."""
        argv = self._validate(command)
        subcommand = argv[1]

        start = time.perf_counter()
        result = await self.sandbox.exec(self.room_id, argv, env=self._env)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        git_metrics.record(elapsed_ms, failed=result.exit_code != 0)

        graph: GraphPayload | None = None
        if (
            subcommand not in READONLY_GIT_SUBCOMMANDS
            and result.exit_code == 0
        ):
            graph = await self.snapshot_graph()

        logger.info(
            "git.exec",
            extra={
                "room_id": self.room_id,
                "argv": argv,
                "exit_code": result.exit_code,
                "graph_refreshed": graph is not None,
            },
        )
        return ExecOutcome(
            action=subcommand,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            argv=argv,
            graph=graph,
        )

    async def snapshot_graph(self) -> GraphPayload:
        """Прочитати актуальний граф через `git log --all`.

        У свіжому репо без коміттів `git log` повертає exit_code != 0 —
        це не помилка, повертаємо порожній граф. Інші збої логуються та
        також зводяться до порожнього графа, щоб не валити основну команду.

        Викликаємо з двох місць: (1) після write-команди у `run()`, щоб
        повернути оновлений граф; (2) при підключенні нового клієнта у
        `on_user_joined`, щоб віддати йому актуальний стан без чекання
        наступної команди.
        """
        try:
            log_result = await self.sandbox.exec(self.room_id, LOG_ARGV)
        except Exception:  # noqa: BLE001 — graph refresh має бути ресілентним
            logger.exception(
                "git.refresh.failed", extra={"room_id": self.room_id}
            )
            return GraphPayload()
        if log_result.exit_code != 0:
            return GraphPayload()
        return parse_graph(log_result.stdout)
