"""Tests for the hidden bot-comment marker and error rendering."""

from app.analysis.pipeline import AnalysisResult
from app.renderer.markdown import (
    BOT_MARKER,
    render_comment,
    render_error,
    render_no_changes,
)


def test_marker_prefixes_full_comment():
    result = AnalysisResult(
        repo="o/r", pr_number=1, head_sha="abc1234",
        files_added=["src/new.ts"], risk_score=10,
        head_node_count=5, head_edge_count=5,
    )
    body = render_comment(result)
    assert body.startswith(BOT_MARKER)
    # The visible heading still comes right after the marker.
    assert "## PR Impact" in body


def test_marker_prefixes_no_changes_comment():
    body = render_no_changes()
    assert body.startswith(BOT_MARKER)
    assert "## PR Impact" in body


def test_render_error_includes_marker_and_details():
    body = render_error("boom: ref not found", head_sha="deadbeef1234")
    assert body.startswith(BOT_MARKER)
    assert "Analysis failed" in body
    assert "deadbee" in body  # short SHA
    assert "boom: ref not found" in body


def test_render_error_truncates_long_messages():
    long_msg = "x" * 5000
    body = render_error(long_msg, head_sha="")
    assert "[truncated]" in body
    # The truncated body stays well under GitHub's 65k comment cap.
    assert len(body) < 2000


def test_render_comment_includes_coupling_alerts():
    result = AnalysisResult(
        repo="o/r", pr_number=1, head_sha="abc1234",
        files_modified=["src/data/cache.ts"],
        risk_score=20,
        coupling_alerts=[
            {
                "dir1": "src/ui",
                "dir2": "src/data",
                "score": 0.55,
                "base_score": 0.15,
                "cross_edges": 7,
            }
        ],
        head_node_count=5, head_edge_count=5,
    )
    body = render_comment(result)
    assert "Coupling Alerts" in body
    assert "src/ui" in body
    assert "src/data" in body
    assert "0.55" in body
