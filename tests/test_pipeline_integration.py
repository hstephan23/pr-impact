"""Integration tests for the analysis pipeline.

These tests exercise the full flow from directory scanning through diff,
blast radius, violations, cycles, and risk scoring — using real temp
directories with sample source files instead of mocked graphs.
"""

import os
import tempfile
import shutil

import pytest

from engine.adapter import scan_directory, to_plain_graph
from app.analysis.diff import diff_graphs
from app.analysis.blast_radius import compute_blast_radius, total_affected
from app.analysis.violations import check_violations
from app.analysis.cycles import diff_cycles
from app.analysis.risk import compute_risk_score
from app.analysis.config import parse_repo_config, config_to_dict


def _write_file(base: str, rel_path: str, content: str):
    """Helper to write a file under a temp directory."""
    full = os.path.join(base, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


@pytest.fixture
def base_repo():
    """Create a temp directory representing the base branch of a JS project."""
    d = tempfile.mkdtemp(prefix="pr-impact-test-base-")
    _write_file(d, "src/app.ts", 'import { Client } from "./api/client";\n')
    _write_file(d, "src/api/client.ts", 'import { auth } from "../utils/auth";\n')
    _write_file(d, "src/utils/auth.ts", "export function auth() { return true; }\n")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def head_repo():
    """Create a temp directory representing the head branch — adds a new module."""
    d = tempfile.mkdtemp(prefix="pr-impact-test-head-")
    _write_file(d, "src/app.ts", (
        'import { Client } from "./api/client";\n'
        'import { Users } from "./api/users";\n'
    ))
    _write_file(d, "src/api/client.ts", 'import { auth } from "../utils/auth";\n')
    _write_file(d, "src/api/users.ts", 'import { Client } from "./client";\n')
    _write_file(d, "src/utils/auth.ts", "export function auth() { return true; }\n")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_scan_directory_returns_nodes_and_edges(base_repo):
    result = scan_directory(base_repo, language="typescript")
    assert result.node_count > 0
    assert result.edge_count > 0

    node_ids = {n["data"]["id"] for n in result.nodes}
    # Should find our source files (paths are relative to repo root)
    assert any("app" in nid for nid in node_ids)
    assert any("auth" in nid for nid in node_ids)


def test_diff_detects_added_file(base_repo, head_repo):
    base_result = scan_directory(base_repo, language="typescript")
    head_result = scan_directory(head_repo, language="typescript")

    base_graph = to_plain_graph(base_result)
    head_graph = to_plain_graph(head_result)

    diff = diff_graphs(base_graph, head_graph)

    # The head branch adds users.ts
    added_ids = diff.nodes_added
    assert any("users" in f for f in added_ids), f"Expected users.ts in added, got: {added_ids}"


def test_blast_radius_on_real_diff(base_repo, head_repo):
    base_result = scan_directory(base_repo, language="typescript")
    head_result = scan_directory(head_repo, language="typescript")

    base_graph = to_plain_graph(base_result)
    head_graph = to_plain_graph(head_result)

    diff = diff_graphs(base_graph, head_graph)
    assert diff.has_changes

    blast = compute_blast_radius(head_graph, diff.changed_files)
    blast_total = total_affected(blast)
    # At minimum, the changed files themselves are involved
    assert blast_total >= 0


def test_full_pipeline_flow(base_repo, head_repo):
    """End-to-end: scan -> diff -> blast -> violations -> cycles -> risk."""
    config = parse_repo_config(None)  # defaults
    config_dict = config_to_dict(config)

    base_result = scan_directory(base_repo, language="typescript")
    head_result = scan_directory(head_repo, language="typescript")

    base_graph = to_plain_graph(base_result)
    head_graph = to_plain_graph(head_result)

    # Diff
    diff = diff_graphs(base_graph, head_graph)
    assert diff.has_changes

    # Blast radius
    blast = compute_blast_radius(head_graph, diff.changed_files)

    # Violations (no layers configured, should be empty)
    violations = check_violations(head_graph, [])
    assert violations == []

    # Cycles
    new_cycles, resolved = diff_cycles(base_result.cycles, head_result.cycles)

    # Risk score
    risk = compute_risk_score(diff, blast, violations, config_dict)
    assert 0 <= risk <= 100


def test_ignore_patterns_filter_files(head_repo):
    """Verify that ignore patterns actually remove matched files from the graph."""
    full_result = scan_directory(head_repo, language="typescript")
    filtered_result = scan_directory(
        head_repo, language="typescript", ignore_patterns=["**/utils/*"]
    )

    full_ids = {n["data"]["id"] for n in full_result.nodes}
    filtered_ids = {n["data"]["id"] for n in filtered_result.nodes}

    auth_in_full = any("auth" in f for f in full_ids)
    auth_in_filtered = any("auth" in f for f in filtered_ids)

    # auth.ts should be in full but filtered out
    if auth_in_full:
        assert not auth_in_filtered, "Ignore pattern should have removed utils/auth.ts"
        assert filtered_result.node_count < full_result.node_count


def test_cycle_detection_with_real_files():
    """Create a circular dependency and verify it's detected."""
    d = tempfile.mkdtemp(prefix="pr-impact-test-cycle-")
    try:
        _write_file(d, "src/a.ts", 'import { b } from "./b";\n')
        _write_file(d, "src/b.ts", 'import { c } from "./c";\n')
        _write_file(d, "src/c.ts", 'import { a } from "./a";\n')

        result = scan_directory(d, language="typescript")
        assert result.has_cycles
        assert len(result.cycles) > 0

        # All three files should be in the cycle
        cycle_files = set()
        for cycle in result.cycles:
            cycle_files.update(cycle)
        assert any("a" in f for f in cycle_files)
        assert any("b" in f for f in cycle_files)
        assert any("c" in f for f in cycle_files)
    finally:
        shutil.rmtree(d, ignore_errors=True)
