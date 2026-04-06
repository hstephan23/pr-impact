"""Architectural violation detection.

Checks imports against user-defined layer ordering. An import going "upward"
(from a deeper layer to a shallower one) is a violation.

Example: if layers = ["ui", "service", "data", "util"], then a file in data/
importing from ui/ is a violation (data is deeper than ui).
"""


def check_violations(
    graph: dict, layers: list[str]
) -> list[dict]:
    """Find all layer violations in the graph.

    Args:
        graph: Dependency graph with nodes and edges.
        layers: Ordered list of layer names, top (shallowest) first.

    Returns:
        List of violation dicts:
        [
            {
                "source": "src/data/cache.ts",
                "target": "src/ui/Avatar.tsx",
                "source_layer": "data",
                "target_layer": "ui",
                "message": "data layer should not depend on ui layer"
            }
        ]
    """
    if not layers:
        return []

    # Build layer rank: lower index = shallower (higher level)
    layer_rank = {name.lower(): i for i, name in enumerate(layers)}

    violations = []
    for edge in graph.get("edges", []):
        source = edge["data"]["source"]
        target = edge["data"]["target"]

        src_layer = _match_layer(source, layer_rank)
        tgt_layer = _match_layer(target, layer_rank)

        if src_layer is None or tgt_layer is None:
            continue

        src_rank = layer_rank[src_layer]
        tgt_rank = layer_rank[tgt_layer]

        # Violation: importing from a shallower layer (lower rank number)
        if src_rank > tgt_rank:
            violations.append({
                "source": source,
                "target": target,
                "source_layer": src_layer,
                "target_layer": tgt_layer,
                "message": f"{src_layer} layer should not depend on {tgt_layer} layer",
            })

    return violations


def _match_layer(filepath: str, layer_rank: dict[str, int]) -> str | None:
    """Match a filepath to a layer name by checking path segments."""
    parts = filepath.replace("\\", "/").split("/")
    for part in parts:
        low = part.lower()
        if low in layer_rank:
            return low
    return None
