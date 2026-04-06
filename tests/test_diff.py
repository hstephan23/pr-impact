"""Tests for graph diffing."""

from app.analysis.diff import diff_graphs


def test_no_changes(sample_graph):
    diff = diff_graphs(sample_graph, sample_graph)
    assert not diff.has_changes
    assert diff.nodes_added == []
    assert diff.nodes_removed == []
    assert diff.edges_added == []
    assert diff.edges_removed == []


def test_added_node(sample_graph):
    head = {
        "nodes": sample_graph["nodes"] + [{"data": {"id": "src/new.ts"}}],
        "edges": sample_graph["edges"],
    }
    diff = diff_graphs(sample_graph, head)
    assert diff.nodes_added == ["src/new.ts"]
    assert diff.nodes_removed == []


def test_removed_node(sample_graph):
    head = {
        "nodes": [n for n in sample_graph["nodes"] if n["data"]["id"] != "src/app.ts"],
        "edges": [e for e in sample_graph["edges"] if e["data"]["source"] != "src/app.ts"],
    }
    diff = diff_graphs(sample_graph, head)
    assert "src/app.ts" in diff.nodes_removed


def test_added_edge(sample_graph):
    new_edge = {"data": {"source": "src/app.ts", "target": "src/utils/auth.ts"}}
    head = {
        "nodes": sample_graph["nodes"],
        "edges": sample_graph["edges"] + [new_edge],
    }
    diff = diff_graphs(sample_graph, head)
    assert ("src/app.ts", "src/utils/auth.ts") in diff.edges_added


def test_changed_files_includes_all(sample_graph):
    head = {
        "nodes": sample_graph["nodes"] + [{"data": {"id": "src/new.ts"}}],
        "edges": sample_graph["edges"] + [
            {"data": {"source": "src/new.ts", "target": "src/utils/auth.ts"}}
        ],
    }
    diff = diff_graphs(sample_graph, head)
    assert "src/new.ts" in diff.changed_files
    assert "src/utils/auth.ts" in diff.changed_files
