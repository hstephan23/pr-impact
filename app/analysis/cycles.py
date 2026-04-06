"""Cycle diffing between base and head graphs.

Compares the sets of strongly connected components (cycles) found in each
branch to determine which cycles are new (introduced by the PR) and which
were resolved.

Cycles are represented as lists of file IDs. Since the same SCC can be
reported in different orderings, we normalize them to sorted frozensets
for comparison.
"""


def _normalize_cycle(cycle: list[str]) -> frozenset[str]:
    """Normalize a cycle to a frozenset for order-independent comparison."""
    return frozenset(cycle)


def diff_cycles(
    base_cycles: list[list[str]],
    head_cycles: list[list[str]],
) -> tuple[list[list[str]], list[list[str]]]:
    """Diff cycles between base and head graphs.

    Args:
        base_cycles: Cycles detected in the base branch.
        head_cycles: Cycles detected in the head branch.

    Returns:
        Tuple of (new_cycles, resolved_cycles):
          - new_cycles: Cycles present in head but not in base (introduced by PR)
          - resolved_cycles: Cycles present in base but not in head (fixed by PR)
    """
    base_set = {_normalize_cycle(c) for c in base_cycles}
    head_set = {_normalize_cycle(c) for c in head_cycles}

    new_frozen = head_set - base_set
    resolved_frozen = base_set - head_set

    # Convert back to sorted lists for stable output
    new_cycles = [sorted(c) for c in new_frozen]
    resolved_cycles = [sorted(c) for c in resolved_frozen]

    # Sort the lists themselves for deterministic ordering
    new_cycles.sort()
    resolved_cycles.sort()

    return new_cycles, resolved_cycles
