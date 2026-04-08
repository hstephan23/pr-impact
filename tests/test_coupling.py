"""Tests for coupling-alert diffing."""

from app.analysis.coupling import diff_couplings


def test_no_couplings_either_side():
    assert diff_couplings([], []) == []


def test_stable_tight_coupling_not_flagged():
    base = [{"dir1": "a", "dir2": "b", "score": 0.5, "cross_edges": 4}]
    head = [{"dir1": "a", "dir2": "b", "score": 0.6, "cross_edges": 5}]
    # Tight in both base and head → not a new alert.
    assert diff_couplings(base, head) == []


def test_newly_tight_coupling_flagged():
    base = [{"dir1": "a", "dir2": "b", "score": 0.1, "cross_edges": 1}]
    head = [{"dir1": "a", "dir2": "b", "score": 0.5, "cross_edges": 5}]
    alerts = diff_couplings(base, head)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["dir1"] == "a"
    assert a["dir2"] == "b"
    assert a["score"] == 0.5
    assert a["base_score"] == 0.1
    assert a["cross_edges"] == 5


def test_brand_new_tight_coupling_flagged():
    head = [{"dir1": "x", "dir2": "y", "score": 0.7, "cross_edges": 10}]
    alerts = diff_couplings([], head)
    assert len(alerts) == 1
    assert alerts[0]["base_score"] == 0.0


def test_low_coupling_not_flagged():
    head = [{"dir1": "x", "dir2": "y", "score": 0.2, "cross_edges": 3}]
    assert diff_couplings([], head) == []


def test_pair_order_insensitive():
    base = [{"dir1": "a", "dir2": "b", "score": 0.5, "cross_edges": 5}]
    head = [{"dir1": "b", "dir2": "a", "score": 0.6, "cross_edges": 6}]
    # Same pair, different ordering — still tight in both, not flagged.
    assert diff_couplings(base, head) == []


def test_alerts_sorted_by_delta():
    base = []
    head = [
        {"dir1": "a", "dir2": "b", "score": 0.45, "cross_edges": 4},
        {"dir1": "c", "dir2": "d", "score": 0.9, "cross_edges": 9},
    ]
    alerts = diff_couplings(base, head)
    assert [a["dir1"] for a in alerts] == ["c", "a"]
