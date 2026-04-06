"""Graph diffing.

Compares two dependency graphs (base vs head) and produces a structured diff:
  - Nodes added / removed
  - Edges added / removed
  - Files whose dependency set changed (even if the file itself didn't)
"""

from dataclasses import dataclass, field


@dataclass
class GraphDiff:
    """Structural diff between two dependency graphs."""
    nodes_added: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    edges_added: list[tuple[str, str]] = field(default_factory=list)
    edges_removed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changed_files(self) -> set[str]:
        """All files involved in any structural change."""
        files = set()
        files.update(self.nodes_added)
        files.update(self.nodes_removed)
        for src, tgt in self.edges_added:
            files.add(src)
            files.add(tgt)
        for src, tgt in self.edges_removed:
            files.add(src)
            files.add(tgt)
        return files

    @property
    def has_changes(self) -> bool:
        return bool(
            self.nodes_added or self.nodes_removed
            or self.edges_added or self.edges_removed
        )


def diff_graphs(base_graph: dict, head_graph: dict) -> GraphDiff:
    """Diff two graph structures.

    Each graph is expected to have:
      - nodes: list of {"data": {"id": str, ...}}
      - edges: list of {"data": {"source": str, "target": str, ...}}

    This matches the format returned by engine.graph.build_graph.
    """
    base_nodes = {n["data"]["id"] for n in base_graph.get("nodes", [])}
    head_nodes = {n["data"]["id"] for n in head_graph.get("nodes", [])}

    base_edges = {
        (e["data"]["source"], e["data"]["target"])
        for e in base_graph.get("edges", [])
    }
    head_edges = {
        (e["data"]["source"], e["data"]["target"])
        for e in head_graph.get("edges", [])
    }

    return GraphDiff(
        nodes_added=sorted(head_nodes - base_nodes),
        nodes_removed=sorted(base_nodes - head_nodes),
        edges_added=sorted(head_edges - base_edges),
        edges_removed=sorted(base_edges - head_edges),
    )
