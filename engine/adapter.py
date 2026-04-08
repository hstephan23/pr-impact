"""Adapter between DepGraph's engine and pr-impact's data model.

DepGraph's build_graph returns a Cytoscape.js-formatted dict with rich metadata.
pr-impact only needs the structural information (nodes, edges, cycles) plus
enough per-node data for risk/impact analysis.

This module provides a clean interface so the rest of pr-impact never
imports from engine.graph or engine.parsers directly.
"""

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

# Add the engine directory to sys.path so graph.py can find parsers.py
# (DepGraph expects them to be siblings, not inside a package)
_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from engine.graph import build_graph, detect_languages  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class GraphResult:
    """Simplified graph result for pr-impact's analysis pipeline."""
    nodes: list[dict]           # [{"data": {"id": ..., ...}}, ...]
    edges: list[dict]           # [{"data": {"source": ..., "target": ..., ...}}, ...]
    cycles: list[list[str]]     # [[file_a, file_b, ...], ...]
    has_cycles: bool
    unused_files: list[str]
    coupling: list[dict]
    node_count: int
    edge_count: int

    # Raw dict for anything else callers might need
    raw: dict = field(default_factory=dict, repr=False)


def scan_directory(
    directory: str,
    *,
    language: str = "auto",
    hide_system: bool = True,
    hide_isolated: bool = False,
    paths: Optional[list[str]] = None,
) -> GraphResult:
    """Scan a directory and build its dependency graph.

    This is the main entry point for pr-impact to call the engine.

    Args:
        directory: Absolute path to the repo root (or cloned branch).
        language: Language mode — "auto" to detect, or specific lang code.
        hide_system: If True, exclude stdlib/external imports.
        hide_isolated: If True, exclude files with no dependencies.
        paths: Optional list of subdirectories to restrict analysis to.
               If provided, uses filter_dir for each path and merges results.

    Returns:
        GraphResult with all structural data needed for analysis.
    """
    # Resolve language flags
    lang_flags = _resolve_lang_flags(directory, language)

    # If specific paths are given, use filter_dir for the first one.
    # Multi-path support would require merging graphs from each path — for
    # now we honor the first entry and emit a warning so users can see that
    # their other paths are being ignored.
    filter_dir = ""
    if paths:
        if paths[0] != ".":
            filter_dir = paths[0]
        if len(paths) > 1:
            logger.warning(
                "Multi-path analysis is not yet supported; using only the first "
                "path %r and ignoring %d additional path(s): %r",
                paths[0],
                len(paths) - 1,
                paths[1:],
            )

    raw = build_graph(
        directory,
        lang_flags=lang_flags,
        hide_system=hide_system,
        hide_isolated=hide_isolated,
        filter_dir=filter_dir,
    )

    return GraphResult(
        nodes=raw.get("nodes", []),
        edges=raw.get("edges", []),
        cycles=raw.get("cycles", []),
        has_cycles=raw.get("has_cycles", False),
        unused_files=raw.get("unused_files", []),
        coupling=raw.get("coupling", []),
        node_count=len(raw.get("nodes", [])),
        edge_count=len(raw.get("edges", [])),
        raw=raw,
    )


def to_plain_graph(result: GraphResult) -> dict:
    """Convert a GraphResult to the plain dict format used by analysis modules.

    Returns {"nodes": [...], "edges": [...]} in the same Cytoscape format.
    """
    return {
        "nodes": result.nodes,
        "edges": result.edges,
    }


def _resolve_lang_flags(directory: str, language: str) -> dict[str, bool]:
    """Resolve language mode into explicit lang_flags dict."""
    if language == "auto":
        detected = detect_languages(directory)
        # Map detection keys (has_py, has_js, ...) to flag keys (show_py, show_js, ...)
        flags = {}
        for key, val in detected.items():
            if key.startswith("has_"):
                flag_key = "show_" + key[4:]
                flags[flag_key] = val
        return flags

    # Specific language — enable just that one
    lang_map = {
        "python": "show_py", "py": "show_py",
        "javascript": "show_js", "js": "show_js",
        "typescript": "show_js", "ts": "show_js",
        "java": "show_java",
        "go": "show_go",
        "rust": "show_rust",
        "c": "show_c",
        "cpp": "show_cpp", "c++": "show_cpp",
        "csharp": "show_cs", "cs": "show_cs",
        "swift": "show_swift",
        "kotlin": "show_kotlin",
        "scala": "show_scala",
        "ruby": "show_ruby",
        "php": "show_php",
        "dart": "show_dart",
        "elixir": "show_elixir",
        "lua": "show_lua",
        "zig": "show_zig",
        "haskell": "show_haskell",
        "r": "show_r",
    }

    flag = lang_map.get(language.lower())
    if flag:
        return {flag: True}

    # Unknown language — fall back to auto-detect
    return _resolve_lang_flags(directory, "auto")
