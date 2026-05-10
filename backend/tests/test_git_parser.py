"""Unit-тести парсера git-output → GraphPayload."""
from __future__ import annotations

from app.git.parser import LOG_FORMAT, parse_graph


def test_log_format_constant_unchanged() -> None:
    """Захист від випадкових змін формату — від нього залежать усі тести."""
    assert LOG_FORMAT == "%H|%P|%D|%s"


def test_parse_empty_log_returns_empty_graph() -> None:
    graph = parse_graph("")
    assert graph.nodes == []
    assert graph.edges == []


def test_parse_single_root_commit() -> None:
    graph = parse_graph("abc123||HEAD -> main|init")
    assert len(graph.nodes) == 1
    n = graph.nodes[0]
    assert n.id == "abc123"
    assert n.label == "init"
    assert n.branch == "main"
    assert n.parents == []
    assert graph.edges == []


def test_parse_linear_history_creates_edges() -> None:
    log = "\n".join(
        [
            "c2|c1|HEAD -> main|second",
            "c1||main|init",
        ]
    )
    graph = parse_graph(log)
    assert {n.id for n in graph.nodes} == {"c1", "c2"}
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source == "c1"
    assert edge.target == "c2"


def test_parse_merge_commit_has_two_edges() -> None:
    log = "merge|p1 p2|HEAD -> main|merge feature"
    graph = parse_graph(log)
    assert len(graph.nodes) == 1
    assert graph.nodes[0].parents == ["p1", "p2"]
    assert {(e.source, e.target) for e in graph.edges} == {
        ("p1", "merge"),
        ("p2", "merge"),
    }


def test_parse_subject_with_pipe_character_preserved() -> None:
    """split('|', 3) гарантує, що '|' у subject не ламає парсинг."""
    graph = parse_graph("abc||main|fix: refactor a | b chain")
    assert graph.nodes[0].label == "fix: refactor a | b chain"


def test_parse_skips_malformed_lines() -> None:
    log = "\n".join(
        [
            "ok||main|good",
            "garbage line without separators",
            "",
            "   ",
            "another||main|also good",
        ]
    )
    graph = parse_graph(log)
    assert {n.id for n in graph.nodes} == {"ok", "another"}


def test_parse_deduplicates_same_sha() -> None:
    log = "\n".join(
        [
            "abc||main|first",
            "abc||main|first",  # дублікат — має ігноруватись
        ]
    )
    graph = parse_graph(log)
    assert len(graph.nodes) == 1


def test_parse_handles_crlf_line_endings() -> None:
    """Sandbox може повернути '\\r\\n' (рідко, але буває)."""
    graph = parse_graph("abc||main|init\r\nzzz|abc|HEAD -> main|next\r\n")
    assert len(graph.nodes) == 2


def test_parse_label_falls_back_to_short_sha_for_empty_subject() -> None:
    graph = parse_graph("abcdef1234567890||main|")
    assert graph.nodes[0].label == "abcdef1"


def test_parse_decoration_head_target_wins_over_other_branches() -> None:
    graph = parse_graph("abc||HEAD -> feature, main|x")
    assert graph.nodes[0].branch == "feature"


def test_parse_decoration_first_branch_when_no_head() -> None:
    graph = parse_graph("abc||main, develop|x")
    assert graph.nodes[0].branch == "main"


def test_parse_decoration_ignores_tags() -> None:
    graph = parse_graph("abc||tag: v1.0, main|x")
    assert graph.nodes[0].branch == "main"


def test_parse_decoration_ignores_remote_tracking() -> None:
    graph = parse_graph("abc||origin/main, main|x")
    assert graph.nodes[0].branch == "main"


def test_parse_detached_head_has_no_branch() -> None:
    graph = parse_graph("abc||HEAD|x")
    assert graph.nodes[0].branch is None


def test_parse_no_decoration_means_no_branch() -> None:
    graph = parse_graph("abc|||x")
    assert graph.nodes[0].branch is None


def test_parse_realistic_topology() -> None:
    """Імітує `git log --all` після:
        init → A → B (main)
                 ↘ C → D (HEAD -> feature)
    """
    log = "\n".join(
        [
            "d|c|HEAD -> feature|D on feature",
            "c|a|feature|C on feature",
            "b|a|main|B on main",
            "a||main|A initial",
        ]
    )
    graph = parse_graph(log)
    ids = {n.id for n in graph.nodes}
    assert ids == {"a", "b", "c", "d"}
    edge_pairs = {(e.source, e.target) for e in graph.edges}
    assert edge_pairs == {("a", "b"), ("a", "c"), ("c", "d")}
    branch_of = {n.id: n.branch for n in graph.nodes}
    assert branch_of["d"] == "feature"  # HEAD ->
    assert branch_of["b"] == "main"
    assert branch_of["a"] == "main"
