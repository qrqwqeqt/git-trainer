"""Unit-тести парсера git-output → GraphPayload."""
from __future__ import annotations

from app.git.parser import LOG_FORMAT, SEP, parse_graph


def _row(sha: str, parents: str, decoration: str, subject: str, author: str = "") -> str:
    """Зручний хелпер: збирає рядок git-log з SEP-розділеними полями."""
    return SEP.join([sha, parents, decoration, subject, author])


def test_log_format_uses_unit_separator() -> None:
    """Якщо хтось зміняє формат — щоб тест явно ламався (нагадування синхр-ти парсер)."""
    assert LOG_FORMAT == "%H\x1f%P\x1f%D\x1f%s\x1f%an"


def test_parse_empty_log_returns_empty_graph() -> None:
    graph = parse_graph("")
    assert graph.nodes == []
    assert graph.edges == []


def test_parse_single_root_commit() -> None:
    graph = parse_graph(_row("abc123", "", "HEAD -> main", "init", "Student"))
    assert len(graph.nodes) == 1
    n = graph.nodes[0]
    assert n.id == "abc123"
    assert n.label == "init"
    assert n.branch == "main"
    assert n.parents == []
    assert n.author == "Student"
    assert graph.edges == []


def test_parse_linear_history_creates_edges() -> None:
    log = "\n".join(
        [
            _row("c2", "c1", "HEAD -> main", "second", "Bob"),
            _row("c1", "", "main", "init", "Alice"),
        ]
    )
    graph = parse_graph(log)
    assert {n.id for n in graph.nodes} == {"c1", "c2"}
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source == "c1"
    assert edge.target == "c2"


def test_parse_merge_commit_has_two_edges() -> None:
    graph = parse_graph(
        _row("merge", "p1 p2", "HEAD -> main", "merge feature", "Bob")
    )
    assert len(graph.nodes) == 1
    assert graph.nodes[0].parents == ["p1", "p2"]
    assert {(e.source, e.target) for e in graph.edges} == {
        ("p1", "merge"),
        ("p2", "merge"),
    }


def test_parse_subject_with_pipe_character_preserved() -> None:
    """SEP \\x1f дозволяє subject-у мати '|' без шкоди для парсингу."""
    graph = parse_graph(
        _row("abc", "", "main", "fix: refactor a | b chain", "Bob")
    )
    assert graph.nodes[0].label == "fix: refactor a | b chain"


def test_parse_skips_malformed_lines() -> None:
    log = "\n".join(
        [
            _row("ok", "", "main", "good", "Alice"),
            "garbage line without separators",
            "",
            "   ",
            _row("another", "", "main", "also good", "Bob"),
        ]
    )
    graph = parse_graph(log)
    assert {n.id for n in graph.nodes} == {"ok", "another"}


def test_parse_deduplicates_same_sha() -> None:
    log = "\n".join(
        [
            _row("abc", "", "main", "first", "Alice"),
            _row("abc", "", "main", "first", "Alice"),  # дублікат
        ]
    )
    graph = parse_graph(log)
    assert len(graph.nodes) == 1


def test_parse_handles_crlf_line_endings() -> None:
    """Sandbox може повернути '\\r\\n' (рідко, але буває)."""
    log = (
        _row("abc", "", "main", "init", "Alice")
        + "\r\n"
        + _row("zzz", "abc", "HEAD -> main", "next", "Bob")
        + "\r\n"
    )
    graph = parse_graph(log)
    assert len(graph.nodes) == 2


def test_parse_label_falls_back_to_short_sha_for_empty_subject() -> None:
    graph = parse_graph(_row("abcdef1234567890", "", "main", "", "Alice"))
    assert graph.nodes[0].label == "abcdef1"


def test_parse_author_optional_for_backwards_compat() -> None:
    """Якщо у вводі лише 4 поля (без %an) — author лишається None."""
    legacy = SEP.join(["abc", "", "main", "init"])  # 4 поля
    graph = parse_graph(legacy)
    assert graph.nodes[0].author is None


def test_parse_decoration_head_target_wins_over_other_branches() -> None:
    graph = parse_graph(_row("abc", "", "HEAD -> feature, main", "x"))
    assert graph.nodes[0].branch == "feature"


def test_parse_decoration_first_branch_when_no_head() -> None:
    graph = parse_graph(_row("abc", "", "main, develop", "x"))
    assert graph.nodes[0].branch == "main"


def test_parse_decoration_ignores_tags() -> None:
    graph = parse_graph(_row("abc", "", "tag: v1.0, main", "x"))
    assert graph.nodes[0].branch == "main"


def test_parse_decoration_ignores_remote_tracking() -> None:
    graph = parse_graph(_row("abc", "", "origin/main, main", "x"))
    assert graph.nodes[0].branch == "main"


def test_parse_detached_head_has_no_branch() -> None:
    graph = parse_graph(_row("abc", "", "HEAD", "x"))
    assert graph.nodes[0].branch is None


def test_parse_no_decoration_means_no_branch() -> None:
    graph = parse_graph(_row("abc", "", "", "x"))
    assert graph.nodes[0].branch is None


def test_parse_realistic_topology() -> None:
    """Імітує `git log --all` після:
        init → A → B (main)
                 ↘ C → D (HEAD -> feature)
    """
    log = "\n".join(
        [
            _row("d", "c", "HEAD -> feature", "D on feature", "Alice"),
            _row("c", "a", "feature", "C on feature", "Alice"),
            _row("b", "a", "main", "B on main", "Bob"),
            _row("a", "", "main", "A initial", "Bob"),
        ]
    )
    graph = parse_graph(log)
    ids = {n.id for n in graph.nodes}
    assert ids == {"a", "b", "c", "d"}
    edge_pairs = {(e.source, e.target) for e in graph.edges}
    assert edge_pairs == {("a", "b"), ("a", "c"), ("c", "d")}
    branch_of = {n.id: n.branch for n in graph.nodes}
    assert branch_of["d"] == "feature"
    assert branch_of["b"] == "main"
    assert branch_of["a"] == "main"
