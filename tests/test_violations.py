"""Tests for architectural violation detection."""

from app.analysis.violations import check_violations


def test_no_layers_no_violations(sample_graph):
    result = check_violations(sample_graph, [])
    assert result == []


def test_detects_upward_violation(layered_graph):
    layers = ["ui", "service", "data", "util"]
    violations = check_violations(layered_graph, layers)

    assert len(violations) == 1
    v = violations[0]
    assert v["source"] == "src/data/userCache.ts"
    assert v["target"] == "src/ui/Button.tsx"
    assert "data" in v["message"]
    assert "ui" in v["message"]


def test_downward_imports_are_fine(layered_graph):
    layers = ["ui", "service", "data", "util"]
    violations = check_violations(layered_graph, layers)

    # Only the upward violation should be flagged
    sources = [v["source"] for v in violations]
    assert "src/ui/Button.tsx" not in sources
    assert "src/service/userService.ts" not in sources


def test_unmatched_files_ignored():
    graph = {
        "nodes": [{"data": {"id": "foo/bar.ts"}}, {"data": {"id": "baz/qux.ts"}}],
        "edges": [{"data": {"source": "foo/bar.ts", "target": "baz/qux.ts"}}],
    }
    violations = check_violations(graph, ["ui", "data"])
    assert violations == []
