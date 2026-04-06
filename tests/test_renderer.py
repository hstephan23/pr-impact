"""Tests for Markdown comment rendering."""

from app.analysis.pipeline import AnalysisResult
from app.renderer.markdown import render_comment, render_no_changes


def test_render_no_changes():
    body = render_no_changes()
    assert "## PR Impact" in body
    assert "No structural" in body


def test_render_comment_basic():
    result = AnalysisResult(
        repo="owner/repo",
        pr_number=42,
        head_sha="abc1234567890",
        files_added=["src/new.ts"],
        risk_score=15,
        blast_radius_total=3,
        head_node_count=50,
        head_edge_count=80,
        analysis_time_ms=250,
    )
    body = render_comment(result)
    assert "## PR Impact" in body
    assert "Risk: 15/100" in body
    assert "abc1234" in body
    assert "`src/new.ts`" in body


def test_render_comment_with_violations():
    result = AnalysisResult(
        repo="owner/repo",
        pr_number=1,
        head_sha="def456",
        violations=[
            {
                "source": "src/data/cache.ts",
                "target": "src/ui/Button.tsx",
                "source_layer": "data",
                "target_layer": "ui",
                "message": "data layer should not depend on ui layer",
            }
        ],
        risk_score=30,
        head_node_count=10,
        head_edge_count=15,
    )
    body = render_comment(result)
    assert "Violation" in body
    assert "data layer should not depend on ui layer" in body


def test_render_comment_with_cycles():
    result = AnalysisResult(
        repo="owner/repo",
        pr_number=1,
        head_sha="ghi789",
        new_cycles=[["a.ts", "b.ts", "c.ts"]],
        resolved_cycles=[["x.ts", "y.ts"]],
        risk_score=40,
        head_node_count=10,
        head_edge_count=15,
    )
    body = render_comment(result)
    assert "a.ts" in body
    assert "b.ts" in body
    assert "Resolved" in body
    assert "~~" in body  # Strikethrough for resolved


def test_render_clean_pr():
    result = AnalysisResult(
        repo="owner/repo",
        pr_number=1,
        head_sha="jkl012",
        files_added=["src/small.ts"],
        risk_score=2,
        blast_radius_total=0,
        head_node_count=10,
        head_edge_count=15,
    )
    body = render_comment(result)
    assert "looks clean" in body.lower() or "Risk: 2/100" in body
