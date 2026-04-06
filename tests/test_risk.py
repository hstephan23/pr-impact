"""Tests for risk scoring."""

from app.analysis.diff import GraphDiff
from app.analysis.risk import compute_risk_score


def test_empty_pr_scores_zero():
    diff = GraphDiff()
    score = compute_risk_score(diff, {}, [], {})
    assert score == 0


def test_large_blast_radius_scores_high():
    diff = GraphDiff(edges_added=[("a", "b")])
    blast = {
        "a": [{"file": f"f{i}.ts", "depth": 1} for i in range(35)]
    }
    score = compute_risk_score(diff, blast, [], {})
    assert score >= 40  # Blast alone should push past 40


def test_violations_increase_score():
    diff = GraphDiff(edges_added=[("a", "b")])
    violations = [
        {"source": "a", "target": "b", "source_layer": "data", "target_layer": "ui",
         "message": "data should not depend on ui"}
    ]
    score_with = compute_risk_score(diff, {}, violations, {})
    score_without = compute_risk_score(diff, {}, [], {})
    assert score_with > score_without


def test_score_capped_at_100():
    diff = GraphDiff(
        nodes_added=[f"n{i}" for i in range(30)],
        edges_added=[(f"n{i}", f"n{i+1}") for i in range(29)],
    )
    blast = {"n0": [{"file": f"f{i}", "depth": i} for i in range(50)]}
    violations = [{"source": f"a{i}", "target": f"b{i}", "source_layer": "x",
                   "target_layer": "y", "message": "bad"} for i in range(10)]
    score = compute_risk_score(diff, blast, violations, {})
    assert score <= 100
