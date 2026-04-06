#!/usr/bin/env python3
"""Standalone test runner — no pytest needed.

Runs the core analysis tests using only stdlib. Tests that require
external dependencies (FastAPI, Jinja2, etc.) are skipped.
"""

import sys
import traceback

PASS = 0
FAIL = 0
SKIP = 0


def run(name, fn):
    global PASS, FAIL, SKIP
    try:
        fn()
        PASS += 1
        print(f"  ✓ {name}")
    except Exception as e:
        FAIL += 1
        print(f"  ✗ {name}: {e}")
        traceback.print_exc(limit=2)


# ============================================================
# Test fixtures
# ============================================================

def sample_graph():
    return {
        "nodes": [
            {"data": {"id": "src/app.ts"}},
            {"data": {"id": "src/utils/auth.ts"}},
            {"data": {"id": "src/api/client.ts"}},
            {"data": {"id": "src/api/users.ts"}},
            {"data": {"id": "src/pages/profile.tsx"}},
        ],
        "edges": [
            {"data": {"source": "src/app.ts", "target": "src/api/client.ts"}},
            {"data": {"source": "src/api/client.ts", "target": "src/utils/auth.ts"}},
            {"data": {"source": "src/api/users.ts", "target": "src/api/client.ts"}},
            {"data": {"source": "src/pages/profile.tsx", "target": "src/api/users.ts"}},
        ],
    }


def layered_graph():
    return {
        "nodes": [
            {"data": {"id": "src/ui/Button.tsx"}},
            {"data": {"id": "src/service/userService.ts"}},
            {"data": {"id": "src/data/userCache.ts"}},
            {"data": {"id": "src/util/format.ts"}},
        ],
        "edges": [
            {"data": {"source": "src/ui/Button.tsx", "target": "src/service/userService.ts"}},
            {"data": {"source": "src/service/userService.ts", "target": "src/data/userCache.ts"}},
            {"data": {"source": "src/data/userCache.ts", "target": "src/util/format.ts"}},
            {"data": {"source": "src/data/userCache.ts", "target": "src/ui/Button.tsx"}},
        ],
    }


# ============================================================
# Diff tests
# ============================================================

from app.analysis.diff import diff_graphs, GraphDiff

print("\n--- Graph Diff ---")


def test_diff_no_changes():
    g = sample_graph()
    diff = diff_graphs(g, g)
    assert not diff.has_changes
    assert diff.nodes_added == []
    assert diff.edges_added == []

run("no changes", test_diff_no_changes)


def test_diff_added_node():
    g = sample_graph()
    h = {"nodes": g["nodes"] + [{"data": {"id": "src/new.ts"}}], "edges": g["edges"]}
    diff = diff_graphs(g, h)
    assert diff.nodes_added == ["src/new.ts"]
    assert diff.nodes_removed == []

run("added node", test_diff_added_node)


def test_diff_removed_node():
    g = sample_graph()
    h = {
        "nodes": [n for n in g["nodes"] if n["data"]["id"] != "src/app.ts"],
        "edges": [e for e in g["edges"] if e["data"]["source"] != "src/app.ts"],
    }
    diff = diff_graphs(g, h)
    assert "src/app.ts" in diff.nodes_removed

run("removed node", test_diff_removed_node)


def test_diff_added_edge():
    g = sample_graph()
    h = {"nodes": g["nodes"], "edges": g["edges"] + [
        {"data": {"source": "src/app.ts", "target": "src/utils/auth.ts"}}
    ]}
    diff = diff_graphs(g, h)
    assert ("src/app.ts", "src/utils/auth.ts") in diff.edges_added

run("added edge", test_diff_added_edge)


def test_diff_changed_files():
    g = sample_graph()
    h = {
        "nodes": g["nodes"] + [{"data": {"id": "src/new.ts"}}],
        "edges": g["edges"] + [
            {"data": {"source": "src/new.ts", "target": "src/utils/auth.ts"}}
        ],
    }
    diff = diff_graphs(g, h)
    assert "src/new.ts" in diff.changed_files
    assert "src/utils/auth.ts" in diff.changed_files

run("changed files", test_diff_changed_files)


# ============================================================
# Blast radius tests
# ============================================================

from app.analysis.blast_radius import compute_blast_radius, total_affected

print("\n--- Blast Radius ---")


def test_blast_single_file():
    g = sample_graph()
    result = compute_blast_radius(g, {"src/utils/auth.ts"})
    affected_files = [e["file"] for e in result["src/utils/auth.ts"]]
    assert "src/api/client.ts" in affected_files
    assert "src/app.ts" in affected_files

run("single file blast", test_blast_single_file)


def test_blast_leaf_file():
    g = sample_graph()
    result = compute_blast_radius(g, {"src/pages/profile.tsx"})
    assert result["src/pages/profile.tsx"] == []

run("leaf file (no dependents)", test_blast_leaf_file)


def test_blast_depth():
    g = sample_graph()
    result = compute_blast_radius(g, {"src/utils/auth.ts"})
    client = next(e for e in result["src/utils/auth.ts"] if e["file"] == "src/api/client.ts")
    assert client["depth"] == 1

run("depth tracking", test_blast_depth)


def test_blast_total_dedup():
    g = sample_graph()
    result = compute_blast_radius(g, {"src/utils/auth.ts", "src/api/client.ts"})
    total = total_affected(result)
    assert total >= 1

run("total deduplication", test_blast_total_dedup)


# ============================================================
# Violation tests
# ============================================================

from app.analysis.violations import check_violations

print("\n--- Violations ---")


def test_violations_no_layers():
    g = sample_graph()
    assert check_violations(g, []) == []

run("no layers = no violations", test_violations_no_layers)


def test_violations_detects_upward():
    g = layered_graph()
    violations = check_violations(g, ["ui", "service", "data", "util"])
    assert len(violations) == 1
    v = violations[0]
    assert v["source"] == "src/data/userCache.ts"
    assert v["target"] == "src/ui/Button.tsx"
    assert "data" in v["message"] and "ui" in v["message"]

run("detects upward violation", test_violations_detects_upward)


def test_violations_downward_ok():
    g = layered_graph()
    violations = check_violations(g, ["ui", "service", "data", "util"])
    sources = [v["source"] for v in violations]
    assert "src/ui/Button.tsx" not in sources

run("downward imports are fine", test_violations_downward_ok)


def test_violations_unmatched_ignored():
    g = {"nodes": [{"data": {"id": "foo/bar.ts"}}], "edges": [
        {"data": {"source": "foo/bar.ts", "target": "baz/qux.ts"}}
    ]}
    assert check_violations(g, ["ui", "data"]) == []

run("unmatched files ignored", test_violations_unmatched_ignored)


# ============================================================
# Risk score tests
# ============================================================

from app.analysis.risk import compute_risk_score

print("\n--- Risk Score ---")


def test_risk_empty():
    diff = GraphDiff()
    assert compute_risk_score(diff, {}, [], {}) == 0

run("empty PR = 0", test_risk_empty)


def test_risk_large_blast():
    diff = GraphDiff(edges_added=[("a", "b")])
    blast = {"a": [{"file": f"f{i}.ts", "depth": 1} for i in range(35)]}
    score = compute_risk_score(diff, blast, [], {})
    assert score >= 40

run("large blast radius scores high", test_risk_large_blast)


def test_risk_violations_increase():
    diff = GraphDiff(edges_added=[("a", "b")])
    violations = [{"source": "a", "target": "b", "source_layer": "data",
                    "target_layer": "ui", "message": "bad"}]
    with_v = compute_risk_score(diff, {}, violations, {})
    without_v = compute_risk_score(diff, {}, [], {})
    assert with_v > without_v

run("violations increase score", test_risk_violations_increase)


def test_risk_capped():
    diff = GraphDiff(
        nodes_added=[f"n{i}" for i in range(30)],
        edges_added=[(f"n{i}", f"n{i+1}") for i in range(29)],
    )
    blast = {"n0": [{"file": f"f{i}", "depth": i} for i in range(50)]}
    violations = [{"source": f"a{i}", "target": f"b{i}", "source_layer": "x",
                    "target_layer": "y", "message": "bad"} for i in range(10)]
    assert compute_risk_score(diff, blast, violations, {}) <= 100

run("capped at 100", test_risk_capped)


# ============================================================
# Cycle diff tests
# ============================================================

from app.analysis.cycles import diff_cycles

print("\n--- Cycle Diff ---")


def test_cycles_no_cycles():
    new, resolved = diff_cycles([], [])
    assert new == [] and resolved == []

run("no cycles both", test_cycles_no_cycles)


def test_cycles_new():
    new, resolved = diff_cycles([], [["a.ts", "b.ts"]])
    assert len(new) == 1 and resolved == []

run("new cycle detected", test_cycles_new)


def test_cycles_resolved():
    new, resolved = diff_cycles([["a.ts", "b.ts"]], [])
    assert new == [] and len(resolved) == 1

run("cycle resolved", test_cycles_resolved)


def test_cycles_order_independent():
    new, resolved = diff_cycles([["c.ts", "a.ts", "b.ts"]], [["a.ts", "b.ts", "c.ts"]])
    assert new == [] and resolved == []

run("order independent comparison", test_cycles_order_independent)


def test_cycles_mixed():
    new, resolved = diff_cycles([["a.ts", "b.ts"]], [["x.ts", "y.ts"]])
    assert len(new) == 1 and len(resolved) == 1

run("mixed new and resolved", test_cycles_mixed)


# ============================================================
# Config tests
# ============================================================

from app.analysis.config import parse_repo_config

print("\n--- Config ---")


def test_config_none():
    c = parse_repo_config(None)
    assert c.paths == ["."] and c.language == "auto"

run("None returns defaults", test_config_none)


def test_config_valid():
    c = parse_repo_config({
        "paths": ["src/"],
        "language": "typescript",
        "layers": ["UI", "Data"],
        "thresholds": {"blast_radius_warn": 5},
    })
    assert c.paths == ["src/"]
    assert c.language == "typescript"
    assert c.layers == ["ui", "data"]
    assert c.blast_radius_warn == 5

run("valid config", test_config_valid)


def test_config_invalid_language():
    c = parse_repo_config({"language": "fortran"})
    assert c.language == "auto"

run("invalid language falls back", test_config_invalid_language)


def test_config_invalid_types():
    c = parse_repo_config({"paths": "not a list", "layers": 42})
    assert c.paths == ["."] and c.layers == []

run("invalid types ignored", test_config_invalid_types)


# ============================================================
# Summary
# ============================================================

print(f"\n{'='*50}")
print(f"  {PASS} passed, {FAIL} failed, {SKIP} skipped")
print(f"{'='*50}")
sys.exit(1 if FAIL else 0)
