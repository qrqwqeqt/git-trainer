"""Парсер виводу git-команд → доменні моделі (GraphPayload, GitEventPayload).

Стратегія: після кожної write-команди (commit, branch, merge, reset, ...)
бекенд виконує `git log --all --format=...` і прогоняє вивід через
`parse_graph`, щоб віддати фронту цілий актуальний граф у GRAPH_UPDATE.

Read-only команди (status, log, diff, show) графа не змінюють — їхній
stdout віддається як `payload.text` у GIT_EVENT і не парситься тут.
"""
from __future__ import annotations

from app.models.schemas import GraphEdge, GraphNode, GraphPayload

# Розділяємо поля Unit Separator-ом (ASCII 0x1F) замість '|', щоб subject
# міг містити будь-які символи (включно з '|') без шкоди для парсингу.
# %D друкує decoration без обрамлення в дужки (на відміну від %d);
# %an — author name (показуємо у tooltip-і фронту).
SEP = "\x1f"
LOG_FORMAT = f"%H{SEP}%P{SEP}%D{SEP}%s{SEP}%an"

# Команда, яку SandboxManager виконує після write-операцій, щоб отримати
# актуальний граф. --all включає всі гілки, --reflog виключаємо: показуємо
# лише те, що видно через ref-и (студенту так зрозуміліше).
LOG_ARGV: list[str] = [
    "git",
    "log",
    "--all",
    "--format=" + LOG_FORMAT,
]


def parse_graph(stdout: str) -> GraphPayload:
    """Розібрати вивід `git log --all --format=...` у GraphPayload.

    Розділювач полів — Unit Separator (\\x1F), тому subject може містити
    будь-які символи, включно з '|'. Порожні та неповні рядки тихо
    ігноруються — це робить парсер стійким до будь-якого «сміття»
    з контейнера.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen: set[str] = set()

    for raw_line in stdout.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            continue
        parts = line.split(SEP)
        if len(parts) < 4:
            continue
        sha = parts[0].strip()
        parents_str = parts[1]
        decoration = parts[2]
        subject = parts[3]
        author = parts[4] if len(parts) >= 5 else ""
        if not sha or sha in seen:
            continue
        seen.add(sha)

        parent_list = parents_str.split() if parents_str.strip() else []
        primary_branch = _primary_branch(decoration)

        nodes.append(
            GraphNode(
                id=sha,
                label=subject or sha[:7],
                branch=primary_branch,
                parents=parent_list,
                author=author or None,
            )
        )
        for parent in parent_list:
            edges.append(GraphEdge(source=parent, target=sha))

    return GraphPayload(nodes=nodes, edges=edges)


def _primary_branch(decoration: str) -> str | None:
    """Витягти «головну» назву гілки з decoration вивода `git log %D`.

    Приклади decoration:
      ""                              → None
      "HEAD -> main"                  → "main"
      "main, origin/main"             → "main"
      "HEAD -> feature, main"         → "feature"  (HEAD перемагає)
      "tag: v1.0, main"               → "main"
      "HEAD"                          → None       (detached HEAD без гілки)

    Логіка: спочатку шукаємо `HEAD -> <name>` (поточна гілка студента), якщо
    такого немає — беремо першу локальну гілку. Теги та remote-tracking
    (з '/') ігноруємо.
    """
    if not decoration.strip():
        return None

    local_branches: list[str] = []
    head_target: str | None = None

    for ref in decoration.split(","):
        ref = ref.strip()
        if not ref:
            continue
        if ref.startswith("HEAD -> "):
            head_target = ref[len("HEAD -> ") :].strip() or None
            if head_target:
                local_branches.append(head_target)
            continue
        if ref == "HEAD":
            continue
        if ref.startswith("tag:"):
            continue
        if "/" in ref:
            # Remote-tracking гілка (напр. origin/main) — у sandbox-і немає
            # remote-ів, але обережно ігноруємо на випадок копії репо.
            continue
        local_branches.append(ref)

    if head_target:
        return head_target
    return local_branches[0] if local_branches else None
