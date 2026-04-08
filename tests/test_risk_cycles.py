"""Tests for the new-cycles component of the risk score."""

from app.analysis.diff import GraphDiff
from app.analysis.risk import compute_risk_score


def test_new_cycles_increase_score():
    diff = GraphDiff(edges_added=[("a", "b")])
    without = compute_risk_score(diff, {}, [], {})
    with_one = compute_risk_score(diff, {}, [], {}, new_cycles=[["a", "b"]])
    assert with_one > without


def test_multiple_cycles_saturate():
    diff = GraphDiff()
    two = compute_risk_score(diff, {}, [], {}, new_cycles=[["a"], ["b"]])
    five = compute_risk_score(
        diff, {}, [], {},
        new_cycles=[["a"], ["b"], ["c"], ["d"], ["e"]],
    )
    # Saturates at 15 for 3 or more cycles.
    assert five == 15
    assert two == 10


def test_no_cycles_no_change():
    diff = GraphDiff()
    assert compute_risk_score(diff, {}, [], {}, new_cycles=None) == 0
    assert compute_risk_score(diff, {}, [], {}, new_cycles=[]) == 0
