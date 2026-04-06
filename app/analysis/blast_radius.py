"""Blast radius computation.

For each changed file, walks the dependency graph forward (downstream) to find
every file transitively affected by the change. Returns results grouped by
depth so the comment can show immediate vs. deep impact.
"""

from collections import deque


def compute_blast_radius(
    graph: dict, changed_files: set[str]
) -> dict[str, list[dict]]:
    """Compute the transitive downstream impact for each changed file.

    Args:
        graph: Head-branch graph with nodes and edges.
        changed_files: Set of file IDs that were structurally changed.

    Returns:
        Dict mapping each changed file to a list of affected files with depth:
        {
            "src/utils/auth.ts": [
                {"file": "src/api/client.ts", "depth": 1},
                {"file": "src/pages/profile.tsx", "depth": 2},
                ...
            ]
        }
    """
    # Build adjacency: target → list of files that import it (dependents)
    dependents: dict[str, list[str]] = {}
    for edge in graph.get("edges", []):
        source = edge["data"]["source"]
        target = edge["data"]["target"]
        # source imports target, so target's dependents include source
        dependents.setdefault(target, []).append(source)

    result = {}
    for file_id in changed_files:
        result[file_id] = _bfs_dependents(file_id, dependents)

    return result


def _bfs_dependents(
    start: str, dependents: dict[str, list[str]]
) -> list[dict]:
    """BFS from start through the dependents graph. Returns affected files with depth."""
    visited = {start}
    queue = deque([(start, 0)])
    affected = []

    while queue:
        current, depth = queue.popleft()
        for dep in dependents.get(current, []):
            if dep not in visited:
                visited.add(dep)
                affected.append({"file": dep, "depth": depth + 1})
                queue.append((dep, depth + 1))

    # Sort by depth, then alphabetically within each depth
    affected.sort(key=lambda x: (x["depth"], x["file"]))
    return affected


def total_affected(blast_radius: dict[str, list[dict]]) -> int:
    """Count total unique files in the blast radius across all changed files."""
    all_affected = set()
    for affected_list in blast_radius.values():
        for entry in affected_list:
            all_affected.add(entry["file"])
    return len(all_affected)
