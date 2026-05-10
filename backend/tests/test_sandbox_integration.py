"""Integration-тести з реальним Docker daemon-ом.

Запуск:
    pytest -m docker

Передумови:
    1. Docker daemon запущений (`docker ps` працює)
    2. Зібраний sandbox image:
           docker build -t git-trainer-sandbox:latest docker/sandbox

Якщо хоча б одна з умов не виконується — тести в цьому файлі skip-аються
з пояснювальним повідомленням замість того, щоб ламати CI.

Що перевіряємо: повний шлях GIT_COMMAND → executor → реальний `docker exec`
у sandbox-контейнері → парсинг `git log --all` → GraphPayload.
"""
from __future__ import annotations

import uuid

import docker
import pytest
import pytest_asyncio

from app.config import Settings
from app.docker.sandbox import SandboxManager
from app.git.executor import GitCommandError, GitCommandExecutor

pytestmark = pytest.mark.docker

SANDBOX_IMAGE = "git-trainer-sandbox:latest"


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


def _image_present(image: str) -> bool:
    try:
        docker.from_env().images.get(image)
        return True
    except Exception:
        return False


@pytest_asyncio.fixture()
async def live_sandbox():
    """Реальний sandbox для одного тесту: start у setup, stop у teardown.

    Skip-аємось у фікстурі, а не на module-level — щоб скіп був помітний у
    звіті pytest-а саме біля того тесту, що його потребує.
    """
    if not _docker_available():
        pytest.skip("docker daemon is not available")
    if not _image_present(SANDBOX_IMAGE):
        pytest.skip(
            f"sandbox image {SANDBOX_IMAGE!r} not found — "
            "run: docker build -t git-trainer-sandbox:latest docker/sandbox"
        )

    settings = Settings(sandbox_image=SANDBOX_IMAGE, max_rooms=10)
    mgr = SandboxManager(settings=settings)
    room_id = f"itest-{uuid.uuid4().hex[:8]}"
    try:
        await mgr.start(room_id)
        yield mgr, room_id
    finally:
        await mgr.stop(room_id)
        await mgr.close()


# ----------------------------------------------------------------------------


async def test_full_flow_init_commit_branch(live_sandbox):
    """init → add → commit → checkout -b feature → commit ⇒ 2 узли в графі."""
    mgr, room_id = live_sandbox
    executor = GitCommandExecutor(room_id, mgr)

    # 1. git init — створює репо, коммітів ще немає.
    init_out = await executor.run("git init")
    assert init_out.exit_code == 0, init_out.stderr
    assert init_out.action == "init"
    assert init_out.graph is not None
    assert init_out.graph.nodes == []

    # 2. Створити робочий файл (через прямий sandbox.exec, поза whitelist).
    create = await mgr.exec(
        room_id, ["sh", "-c", "echo hello > file.txt"]
    )
    assert create.exit_code == 0, create.stderr

    # 3. git add file.txt
    add_out = await executor.run("git add file.txt")
    assert add_out.exit_code == 0, add_out.stderr

    # 4. Перший комміт.
    commit_out = await executor.run("git commit -m init")
    assert commit_out.exit_code == 0, commit_out.stderr
    assert commit_out.action == "commit"
    assert commit_out.graph is not None
    assert len(commit_out.graph.nodes) == 1
    first = commit_out.graph.nodes[0]
    assert first.label == "init"
    assert first.branch == "main"
    assert len(first.id) == 40  # SHA-1 у hex

    # 5. Створюємо нову гілку feature.
    co = await executor.run("git checkout -b feature")
    assert co.exit_code == 0, co.stderr
    assert co.graph is not None
    assert len(co.graph.nodes) == 1
    # Той самий комміт — але тепер HEAD -> feature.
    assert co.graph.nodes[0].branch == "feature"

    # 6. Другий комміт уже на гілці feature.
    await mgr.exec(room_id, ["sh", "-c", "echo more > more.txt"])
    await executor.run("git add more.txt")
    second = await executor.run("git commit -m feature-work")
    assert second.exit_code == 0, second.stderr
    assert second.graph is not None
    assert len(second.graph.nodes) == 2

    new_node = next(n for n in second.graph.nodes if first.id in n.parents)
    assert new_node.branch == "feature"
    assert new_node.label == "feature-work"
    assert any(
        e.source == first.id and e.target == new_node.id
        for e in second.graph.edges
    )


async def test_invalid_subcommand_rejected_before_sandbox(live_sandbox):
    """Команди поза whitelist не доходять до контейнера (валідація на хості)."""
    mgr, room_id = live_sandbox
    executor = GitCommandExecutor(room_id, mgr)
    with pytest.raises(GitCommandError):
        await executor.run("git push origin main")


async def test_status_in_unborn_repo_returns_error(live_sandbox):
    """Без `git init` команда `git status` падає, але WS-протокол вживу:
    повертає ExecOutcome з exit_code != 0, action="status", graph=None.
    """
    mgr, room_id = live_sandbox
    executor = GitCommandExecutor(room_id, mgr)
    out = await executor.run("git status")
    assert out.action == "status"
    assert out.exit_code != 0
    assert "not a git repository" in out.stderr.lower()
    assert out.graph is None  # status — read-only


async def test_network_isolation_enforced(live_sandbox):
    """Перевіряємо, що network=none дійсно діє: будь-яка зовнішня IP-операція
    має фейлитись усередині контейнера. Це санітарна перевірка кофігурації
    запуску, а не Git-логіки.
    """
    mgr, room_id = live_sandbox
    # ip route не має жодного зовнішнього маршруту в network=none.
    result = await mgr.exec(room_id, ["sh", "-c", "ip route 2>&1 || true"])
    assert "default" not in result.stdout, (
        "sandbox unexpectedly has a default route — network isolation is broken"
    )
