"""Coupling-alert diffing.

The engine computes a "coupling score" per directory pair — a ratio of
cross-directory edges to the directory pair's total edges. This module
compares the base and head coupling lists and surfaces directory pairs
that became tightly coupled in the head branch (i.e., a PR that introduces
significant new cross-directory dependencies).
"""

# Default threshold: a coupling score at or above this is considered "tight".
# Kept intentionally conservative so only meaningful shifts surface.
TIGHT_COUPLING_THRESHOLD = 0.4


def diff_couplings(
    base_couplings: list[dict],
    head_couplings: list[dict],
    threshold: float = TIGHT_COUPLING_THRESHOLD,
) -> list[dict]:
    """Return directory pairs that became tightly coupled in the head branch.

    A pair is flagged if its head score is >= threshold AND its base score
    was below threshold (including pairs that didn't exist in the base).

    Args:
        base_couplings: Engine coupling list from the base branch.
        head_couplings: Engine coupling list from the head branch.
        threshold: Coupling score at or above which a pair is "tight".

    Returns:
        List of alert dicts, sorted by the largest score delta first:
        [
            {
                "dir1": "src/ui",
                "dir2": "src/data",
                "score": 0.52,
                "base_score": 0.18,
                "cross_edges": 9,
            },
            ...
        ]
    """
    base_by_pair: dict[tuple[str, str], float] = {}
    for c in base_couplings or []:
        key = _pair_key(c)
        if key is not None:
            base_by_pair[key] = float(c.get("score", 0) or 0)

    alerts: list[dict] = []
    for c in head_couplings or []:
        key = _pair_key(c)
        if key is None:
            continue
        head_score = float(c.get("score", 0) or 0)
        if head_score < threshold:
            continue
        base_score = base_by_pair.get(key, 0.0)
        if base_score >= threshold:
            continue
        alerts.append({
            "dir1": c.get("dir1", ""),
            "dir2": c.get("dir2", ""),
            "score": round(head_score, 3),
            "base_score": round(base_score, 3),
            "cross_edges": int(c.get("cross_edges", 0) or 0),
        })

    alerts.sort(key=lambda a: (a["score"] - a["base_score"]), reverse=True)
    return alerts


def _pair_key(c: dict) -> tuple[str, str] | None:
    """Canonical key for a coupling entry (order-insensitive on the pair)."""
    d1 = c.get("dir1")
    d2 = c.get("dir2")
    if not isinstance(d1, str) or not isinstance(d2, str):
        return None
    return tuple(sorted((d1, d2)))
