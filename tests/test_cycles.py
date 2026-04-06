"""Tests for cycle diffing."""

from app.analysis.cycles import diff_cycles


def test_no_cycles_both():
    new, resolved = diff_cycles([], [])
    assert new == []
    assert resolved == []


def test_new_cycle_detected():
    base = []
    head = [["a.ts", "b.ts", "c.ts"]]
    new, resolved = diff_cycles(base, head)
    assert len(new) == 1
    assert set(new[0]) == {"a.ts", "b.ts", "c.ts"}
    assert resolved == []


def test_cycle_resolved():
    base = [["a.ts", "b.ts"]]
    head = []
    new, resolved = diff_cycles(base, head)
    assert new == []
    assert len(resolved) == 1
    assert set(resolved[0]) == {"a.ts", "b.ts"}


def test_same_cycle_different_order():
    base = [["c.ts", "a.ts", "b.ts"]]
    head = [["a.ts", "b.ts", "c.ts"]]
    new, resolved = diff_cycles(base, head)
    assert new == []
    assert resolved == []


def test_mixed_new_and_resolved():
    base = [["a.ts", "b.ts"]]
    head = [["x.ts", "y.ts"]]
    new, resolved = diff_cycles(base, head)
    assert len(new) == 1
    assert set(new[0]) == {"x.ts", "y.ts"}
    assert len(resolved) == 1
    assert set(resolved[0]) == {"a.ts", "b.ts"}


def test_unchanged_cycles_ignored():
    base = [["a.ts", "b.ts"], ["x.ts", "y.ts"]]
    head = [["a.ts", "b.ts"], ["x.ts", "y.ts"], ["m.ts", "n.ts"]]
    new, resolved = diff_cycles(base, head)
    assert len(new) == 1
    assert set(new[0]) == {"m.ts", "n.ts"}
    assert resolved == []
