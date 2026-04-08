"""Risk scoring.

Produces a single 0-100 score summarizing the structural risk of a PR.
Higher = more dangerous. The score is a weighted combination of:

  - Blast radius size (how many files are transitively affected)
  - New cycles introduced
  - Architectural violations introduced
  - Depth of impact (shallow changes = lower risk)
  - Number of structural changes (edges added/removed)
"""

from app.analysis.diff import GraphDiff


def compute_risk_score(
    diff: GraphDiff,
    blast_radius: dict[str, list[dict]],
    violations: list[dict],
    config: dict,
    new_cycles: list[list[str]] | None = None,
) -> int:
    """Compute a 0-100 risk score for the PR.

    Args:
        diff: Structural diff between base and head graphs.
        blast_radius: Per-file downstream impact.
        violations: Architectural violations found.
        config: Repo config (thresholds, etc.).
        new_cycles: Cycles introduced by this PR (optional).

    Returns:
        Integer risk score, 0 (safe) to 100 (dangerous).
    """
    thresholds = config.get("thresholds", {})
    blast_warn = thresholds.get("blast_radius_warn", 10)
    blast_critical = thresholds.get("blast_radius_critical", 30)

    score = 0.0

    # --- Blast radius component (0-40 points) ---
    unique_affected = set()
    max_depth = 0
    for affected_list in blast_radius.values():
        for entry in affected_list:
            unique_affected.add(entry["file"])
            max_depth = max(max_depth, entry["depth"])

    total = len(unique_affected)
    if total >= blast_critical:
        score += 40
    elif total >= blast_warn:
        score += 15 + 25 * ((total - blast_warn) / max(1, blast_critical - blast_warn))
    elif total > 0:
        score += 15 * (total / max(1, blast_warn))

    # --- Depth component (0-15 points) ---
    if max_depth >= 5:
        score += 15
    elif max_depth >= 3:
        score += 8
    elif max_depth >= 1:
        score += 3

    # --- Violations component (0-25 points) ---
    v_count = len(violations)
    if v_count >= 5:
        score += 25
    elif v_count > 0:
        score += 5 * v_count

    # --- Structural churn (0-20 points) ---
    edge_changes = len(diff.edges_added) + len(diff.edges_removed)
    node_changes = len(diff.nodes_added) + len(diff.nodes_removed)
    churn = edge_changes + node_changes
    if churn >= 20:
        score += 20
    elif churn > 0:
        score += churn

    # --- New cycles (0-15 points) ---
    # A fresh dependency cycle is always a meaningful signal, regardless of
    # size. The score rises quickly for the first few cycles, then saturates.
    n_cycles = len(new_cycles or [])
    if n_cycles >= 3:
        score += 15
    elif n_cycles > 0:
        score += 5 * n_cycles

    return min(100, max(0, round(score)))
