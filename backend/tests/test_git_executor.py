"""Unit-тести GitCommandExecutor (з мок-SandboxManager-ом)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.docker.sandbox import ExecResult, SandboxError
from app.git.executor import (
    ALLOWED_GIT_COMMANDS,
    READONLY_GIT_SUBCOMMANDS,
    ExecOutcome,
    GitCommandError,
    GitCommandExecutor,
)


@pytest.fixture()
def fake_sandbox():
    sandbox = MagicMock()
    sandbox.exec = AsyncMock()
    return sandbox


# --------------------------- validation ---------------------------


async def test_run_rejects_non_git_command(fake_sandbox):
    executor = GitCommandExecutor("r1", fake_sandbox)
    with pytest.raises(GitCommandError):
        await executor.run("ls -la")
    fake_sandbox.exec.assert_not_called()


async def test_run_rejects_unwhitelisted_subcommand(fake_sandbox):
    executor = GitCommandExecutor("r1", fake_sandbox)
    with pytest.raises(GitCommandError):
        await executor.run("git push origin main")
    fake_sandbox.exec.assert_not_called()


@pytest.mark.parametrize(
    "bad_command",
    [
        "git status; echo hacked",
        "git status && rm -rf /",
        "git status | grep main",
        "git status > /tmp/leak",
        "git log `whoami`",
        "git log $(echo evil)",
    ],
)
async def test_run_rejects_shell_metacharacters(fake_sandbox, bad_command):
    executor = GitCommandExecutor("r1", fake_sandbox)
    with pytest.raises(GitCommandError):
        await executor.run(bad_command)
    fake_sandbox.exec.assert_not_called()


async def test_run_rejects_missing_subcommand(fake_sandbox):
    executor = GitCommandExecutor("r1", fake_sandbox)
    with pytest.raises(GitCommandError):
        await executor.run("git")


async def test_run_rejects_empty_string(fake_sandbox):
    executor = GitCommandExecutor("r1", fake_sandbox)
    with pytest.raises(GitCommandError):
        await executor.run("")


async def test_run_rejects_invalid_quoting(fake_sandbox):
    executor = GitCommandExecutor("r1", fake_sandbox)
    with pytest.raises(GitCommandError):
        await executor.run("git commit -m 'unclosed")


# ---------------------------- happy paths ---------------------------


async def test_run_status_no_graph_refresh(fake_sandbox):
    """Read-only команда → exec викликається один раз, граф не оновлюється."""
    fake_sandbox.exec.return_value = ExecResult(
        exit_code=0, stdout="On branch main\n", stderr=""
    )
    executor = GitCommandExecutor("r1", fake_sandbox)
    outcome = await executor.run("git status")

    assert isinstance(outcome, ExecOutcome)
    assert outcome.action == "status"
    assert outcome.exit_code == 0
    assert outcome.stdout == "On branch main\n"
    assert outcome.argv == ["git", "status"]
    assert outcome.graph is None
    fake_sandbox.exec.assert_called_once_with("r1", ["git", "status"])


async def test_run_commit_refreshes_graph(fake_sandbox):
    fake_sandbox.exec.side_effect = [
        ExecResult(0, "[main abc123] init\n", ""),
        ExecResult(0, "abc123\x1f\x1fHEAD -> main\x1finit\x1fStudent\n", ""),
    ]
    executor = GitCommandExecutor("r1", fake_sandbox)
    outcome = await executor.run("git commit -m init")

    assert outcome.action == "commit"
    assert outcome.exit_code == 0
    assert outcome.graph is not None
    assert len(outcome.graph.nodes) == 1
    assert outcome.graph.nodes[0].id == "abc123"
    assert outcome.graph.nodes[0].branch == "main"

    # Перший виклик — сама команда, другий — git log refresh.
    assert fake_sandbox.exec.call_count == 2
    second_call_argv = fake_sandbox.exec.call_args_list[1].args[1]
    assert second_call_argv[:2] == ["git", "log"]
    assert "--all" in second_call_argv


async def test_run_failed_write_skips_graph_refresh(fake_sandbox):
    """Якщо команда вернула не-0 exit, граф не оновлюємо (нема чого показувати)."""
    fake_sandbox.exec.return_value = ExecResult(
        exit_code=1, stdout="", stderr="fatal: pathspec 'foo' did not match\n"
    )
    executor = GitCommandExecutor("r1", fake_sandbox)
    outcome = await executor.run("git add foo")

    assert outcome.exit_code == 1
    assert outcome.stderr.startswith("fatal:")
    assert outcome.graph is None
    fake_sandbox.exec.assert_called_once()


async def test_run_log_command_returns_no_graph(fake_sandbox):
    """`git log` сам по собі read-only — не тригерить додатковий refresh."""
    fake_sandbox.exec.return_value = ExecResult(
        0, "commit abc123 (HEAD -> main)\n", ""
    )
    executor = GitCommandExecutor("r1", fake_sandbox)
    outcome = await executor.run("git log --oneline")

    assert outcome.action == "log"
    assert outcome.graph is None
    fake_sandbox.exec.assert_called_once()


async def test_run_graph_refresh_returns_empty_for_unborn_repo(fake_sandbox):
    """Свіжий `git init` без коммітів → log падає, граф порожній."""
    fake_sandbox.exec.side_effect = [
        ExecResult(0, "Initialized empty Git repository\n", ""),
        ExecResult(128, "", "fatal: your current branch does not have any commits yet\n"),
    ]
    executor = GitCommandExecutor("r1", fake_sandbox)
    outcome = await executor.run("git init")

    assert outcome.action == "init"
    assert outcome.exit_code == 0
    assert outcome.graph is not None
    assert outcome.graph.nodes == []
    assert outcome.graph.edges == []


async def test_run_graph_refresh_swallows_sandbox_errors(fake_sandbox):
    """Невдалий refresh не повинен ламати основну команду."""
    fake_sandbox.exec.side_effect = [
        ExecResult(0, "[main abc] init\n", ""),
        SandboxError("daemon died"),
    ]
    executor = GitCommandExecutor("r1", fake_sandbox)
    outcome = await executor.run("git commit -m init")

    assert outcome.exit_code == 0
    assert outcome.graph is not None
    assert outcome.graph.nodes == []  # порожній граф як fallback


async def test_run_propagates_sandbox_error_for_main_command(fake_sandbox):
    """Якщо помирає сама команда (не refresh) — піднімаємо помилку наверх."""
    fake_sandbox.exec.side_effect = SandboxError("no sandbox running")
    executor = GitCommandExecutor("r1", fake_sandbox)
    with pytest.raises(SandboxError):
        await executor.run("git status")


# ---------------------------- consistency ---------------------------


def test_readonly_subcommands_are_subset_of_allowed():
    """Захист від помилки: read-only підкоманди мають бути валідними git-командами."""
    assert READONLY_GIT_SUBCOMMANDS <= ALLOWED_GIT_COMMANDS
