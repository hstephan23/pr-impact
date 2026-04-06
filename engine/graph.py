"""Core graph-building engine for DepGraph.

Scans source files, resolves imports using the language-specific parsers from
``parsers.py``, detects cycles (Tarjan's SCC), and computes per-node metrics
(depth, impact, stability, coupling).

This module uses only the Python standard library (plus ``parsers``) so it can
be imported by the CLI without Flask.
"""
from __future__ import annotations

import json
import logging
import os
import hashlib
from typing import Any, Optional, Dict, List, Set, Tuple

log = logging.getLogger('depgraph.graph')

from parsers import (
    # Regex patterns
    INCLUDE_RE, JS_IMPORT_RE,
    PY_FROM_IMPORT_RE, PY_IMPORT_RE,
    JAVA_IMPORT_RE,
    GO_IMPORT_RE, GO_IMPORT_PATH_RE,
    RUST_USE_RE, RUST_MOD_RE, RUST_EXTERN_RE,
    CS_USING_RE,
    SWIFT_IMPORT_RE,
    RUBY_REQUIRE_RE, RUBY_REQUIRE_RELATIVE_RE,
    KOTLIN_IMPORT_RE,
    SCALA_IMPORT_RE,
    PHP_USE_RE, PHP_REQUIRE_RE,
    DART_IMPORT_RE,
    ELIXIR_ALIAS_RE,
    LUA_REQUIRE_RE,
    ZIG_IMPORT_RE,
    HASKELL_IMPORT_RE,
    R_LIBRARY_RE, R_SOURCE_RE,
    # Extension tuples
    C_EXTENSIONS, H_EXTENSIONS, CPP_EXTENSIONS, JS_EXTENSIONS,
    PY_EXTENSIONS, JAVA_EXTENSIONS, GO_EXTENSIONS, RUST_EXTENSIONS,
    CS_EXTENSIONS, SWIFT_EXTENSIONS, RUBY_EXTENSIONS,
    KOTLIN_EXTENSIONS, SCALA_EXTENSIONS, PHP_EXTENSIONS,
    DART_EXTENSIONS, ELIXIR_EXTENSIONS,
    LUA_EXTENSIONS, ZIG_EXTENSIONS, HASKELL_EXTENSIONS, R_EXTENSIONS,
    # Helpers
    collapse_py_multiline_imports,
    # Resolution functions
    resolve_js_import, resolve_py_import, resolve_java_import,
    parse_go_mod, resolve_go_import,
    resolve_rust_mod,
    build_cs_namespace_map, resolve_cs_using,
    resolve_swift_import,
    resolve_ruby_require,
    resolve_kotlin_import,
    resolve_scala_import,
    build_php_namespace_map, resolve_php_use, resolve_php_require,
    resolve_dart_import,
    resolve_elixir_module,
    resolve_lua_require,
    resolve_zig_import,
    resolve_haskell_import,
    resolve_r_source,
    # Stdlib sets for library/require filtering
    R_STDLIB,
    # Resolution cache
    ResolutionCache,
)


# =========================================================================
# Palette & colouring
# =========================================================================

_PALETTE = [
    "#6366f1", "#818cf8", "#8b5cf6", "#7c3aed", "#6d28d9",
    "#3b82f6", "#60a5fa", "#0ea5e9", "#06b6d4", "#14b8a6",
    "#0d9488", "#475569", "#64748b", "#7dd3fc", "#a78bfa",
    "#38bdf8", "#2dd4bf", "#a5b4fc", "#94a3b8", "#5eead4",
]

# Per-language colors — loosely based on each language's brand/community colour.
# Used when the caller opts in to language-aware colouring.
LANGUAGE_COLORS = {
    "c":       "#555555",
    "h":       "#6e6e6e",
    "cpp":     "#00599c",
    "js":      "#f7df1e",
    "py":      "#3776ab",
    "java":    "#e76f00",
    "go":      "#00add8",
    "rust":    "#ce422b",
    "cs":      "#68217a",
    "swift":   "#f05138",
    "ruby":    "#cc342d",
    "kotlin":  "#7f52ff",
    "scala":   "#dc322f",
    "php":     "#777bb4",
    "dart":    "#0175c2",
    "elixir":  "#6e4a7e",
    "lua":     "#000080",
    "zig":     "#f7a41d",
    "haskell": "#5e5086",
    "r":       "#276dc3",
}

# =========================================================================
# Risk-based colour system
# =========================================================================
# Color encodes importance + risk so your eyes go straight to problems.

# Load from shared/constants.json — single source of truth for all frontends.
_SHARED_CONSTANTS_PATH = os.path.join(os.path.dirname(__file__), "shared", "constants.json")
if os.path.isfile(_SHARED_CONSTANTS_PATH):
    with open(_SHARED_CONSTANTS_PATH, "r") as _f:
        _SHARED = json.loads(_f.read())
    RISK_COLORS: Dict[str, str] = _SHARED["risk_colors"]
    RISK_LABELS: Dict[str, str] = _SHARED["risk_labels"]
else:
    # Fallback so the module still works if the JSON file is missing.
    RISK_COLORS = {
        "critical": "#ef4444", "high": "#f97316", "warning": "#eab308",
        "normal": "#3b82f6", "entry": "#22c55e", "system": "#6b7280",
    }
    RISK_LABELS = {
        "critical": "Critical / God file", "high": "High influence",
        "warning": "High dependency", "normal": "Normal",
        "entry": "Entry point / leaf", "system": "System / external",
    }


def classify_node_risk(node_data: Dict[str, Any], total_nodes: int) -> str:
    """Assign a risk category to a single node.

    Returns one of: ``"critical"``, ``"high"``, ``"warning"``, ``"normal"``,
    ``"entry"``, ``"system"``.

    The classification uses thresholds that adapt to graph size so a 10-file
    project doesn't treat everything as critical.
    """
    in_deg = node_data.get("in_degree", 0)
    out_deg = node_data.get("out_degree", 0)
    in_cycle = node_data.get("in_cycle", False)
    reach_pct = node_data.get("reach_pct", 0)
    nid = node_data.get("id", "")

    # System / external nodes (identified by a leading "system:" or no language)
    if nid.startswith("system:") or nid.startswith("<"):
        return "system"

    # Adaptive thresholds based on graph size
    if total_nodes <= 10:
        critical_in = 5
        high_in = 3
        warning_out = 4
    elif total_nodes <= 50:
        critical_in = 8
        high_in = 5
        warning_out = 6
    else:
        critical_in = max(10, total_nodes // 5)
        high_in = max(5, total_nodes // 10)
        warning_out = max(8, total_nodes // 8)

    # 1. Critical: cycle members, or extreme inbound / reach
    if in_cycle or in_deg >= critical_in or reach_pct >= 50:
        return "critical"

    # 2. High influence: significant inbound
    if in_deg >= high_in or reach_pct >= 30:
        return "high"

    # 3. Warning: too many outbound (fragile / over-coupled)
    if out_deg >= warning_out:
        return "warning"

    # 4. Entry points / leaves: zero inbound
    if in_deg == 0:
        return "entry"

    # 5. Normal
    return "normal"


def node_size_for_degree(in_degree: int, total_nodes: int) -> int:
    """Return a node size (diameter) scaled by inbound degree.

    Returns ``80 + in_degree * 40``, compatible with the existing
    Cytoscape ``data(size)`` convention (baseline 80).
    """
    return 80 + in_degree * 40

# =========================================================================
# File filtering helpers
# =========================================================================

# Central registry: maps each ``show_*`` flag name to the file extensions it
# controls.  Adding a new language only requires a single entry here — every
# filter function, ``collect_source_files``, and ``detect_languages`` picks
# it up automatically.
LANG_EXTENSION_TABLE = [
    ("show_c",       C_EXTENSIONS),
    ("show_h",       H_EXTENSIONS),
    ("show_cpp",     CPP_EXTENSIONS),
    ("show_js",      JS_EXTENSIONS),
    ("show_py",      PY_EXTENSIONS),
    ("show_java",    JAVA_EXTENSIONS),
    ("show_go",      GO_EXTENSIONS),
    ("show_rust",    RUST_EXTENSIONS),
    ("show_cs",      CS_EXTENSIONS),
    ("show_swift",   SWIFT_EXTENSIONS),
    ("show_ruby",    RUBY_EXTENSIONS),
    ("show_kotlin",  KOTLIN_EXTENSIONS),
    ("show_scala",   SCALA_EXTENSIONS),
    ("show_php",     PHP_EXTENSIONS),
    ("show_dart",    DART_EXTENSIONS),
    ("show_elixir",  ELIXIR_EXTENSIONS),
    ("show_lua",     LUA_EXTENSIONS),
    ("show_zig",     ZIG_EXTENSIONS),
    ("show_haskell", HASKELL_EXTENSIONS),
    ("show_r",       R_EXTENSIONS),
]

# Directories to skip when a given language flag is enabled.
LANG_SKIP_DIRS = {
    "show_js":     {'node_modules'},
    "show_py":     {'__pycache__', '.venv', 'venv', '.tox', '.eggs',
                    '*.egg-info'},
    "show_go":     {'vendor'},
    "show_rust":   {'target'},
    "show_cs":     {'bin', 'obj', 'packages', '.vs'},
    "show_ruby":   {'vendor', '.bundle'},
    "show_kotlin": {'build'},
    "show_scala":  {'target', '.bsp', '.metals'},
    "show_php":    {'vendor'},
    "show_dart":   {'.dart_tool', 'build', '.pub-cache'},
    "show_elixir": {'_build', 'deps', '.elixir_ls'},
    "show_lua":     {'luarocks', '.luarocks'},
    "show_zig":     {'zig-cache', 'zig-out'},
    "show_haskell": {'.stack-work', 'dist-newstyle', 'dist', '.cabal-sandbox'},
    "show_r":       {'renv', 'packrat'},
}

# Map file extensions → short language key (used for node metadata).
_EXT_TO_LANG = {}
for _flag, _exts in LANG_EXTENSION_TABLE:
    _lang = _flag[len("show_"):]          # "show_py" → "py"
    for _ext in _exts:
        _EXT_TO_LANG[_ext] = _lang


def _lang_for_path(filepath: str) -> Optional[str]:
    """Return the short language key for *filepath*, or ``None``."""
    _, ext = os.path.splitext(filepath)
    return _EXT_TO_LANG.get(ext)


def _dir_color(filepath: str) -> str:
    """Return a deterministic color for *filepath*'s directory."""
    dirname = os.path.dirname(filepath) or "."
    hash_val = int(hashlib.md5(dirname.encode('utf-8')).hexdigest(), 16)
    return _PALETTE[hash_val % len(_PALETTE)]


def _color_for_path(filepath: str) -> str:
    """Return a deterministic color for *filepath*.

    Uses the file's directory to pick a palette colour so files in the
    same folder share a colour.
    """
    return _dir_color(filepath)


def _should_skip_dir(name: str) -> bool:
    """Return True for directories that should be excluded from scanning."""
    lower = name.lower()
    return lower.startswith('test') or 'test' in lower or 'cmake' in lower


def _should_skip_file(name: str) -> bool:
    """Return True for files that should be excluded from scanning."""
    lower = name.lower()
    return 'test' in lower or 'cmake' in lower


def _wanted_extension(filename: str, lang_flags: Dict[str, bool]) -> bool:
    """Check whether *filename* has an extension enabled in *lang_flags*.

    *lang_flags* is a dict mapping ``show_*`` keys to booleans, e.g.
    ``{"show_py": True, "show_js": False, ...}``.
    """
    for flag, exts in LANG_EXTENSION_TABLE:
        if lang_flags.get(flag) and filename.endswith(exts):
            return True
    return False


def _include_target_excluded(filename: str, lang_flags: Dict[str, bool]) -> bool:
    """Return True if an include/import target should be excluded.

    A target is excluded when its extension belongs to a language group that
    is *not* enabled in *lang_flags*.
    """
    for flag, exts in LANG_EXTENSION_TABLE:
        if filename.endswith(exts) and not lang_flags.get(flag):
            return True
    return False


def _resolve_c_include(
    included: str,
    source_file: str,
    known_files: Set[str],
    _basename_index: Optional[Dict[str, List[str]]] = None
) -> Optional[str]:
    """Resolve a C/C++ #include path to a known project file.

    Search order:
      1. Relative to the including file's directory  (e.g. src/main.c → src/utils.h)
      2. Exact match as a project-relative path       (e.g. inc/utils.h)
      3. Basename match anywhere in the project        (e.g. utils.h → inc/utils.h)

    Returns the resolved relative path, or None if not found.
    """
    # 1. Relative to the including file's directory
    source_dir = os.path.dirname(source_file)
    if source_dir:
        candidate = os.path.normpath(os.path.join(source_dir, included))
    else:
        candidate = os.path.normpath(included)
    if candidate in known_files:
        return candidate

    # 2. Exact match as project-relative path
    normed = os.path.normpath(included)
    if normed in known_files:
        return normed

    # 3. Basename match — find any file in the project with the same name
    basename = os.path.basename(included)
    if _basename_index is not None:
        matches = _basename_index.get(basename)
        if matches:
            # Prefer the shortest path (closest to root) if multiple matches
            return min(matches, key=len)
    else:
        for kf in known_files:
            if os.path.basename(kf) == basename:
                return kf

    return None


# =========================================================================
# Tarjan's strongly-connected-components algorithm
# =========================================================================

def find_sccs(adj: Dict[str, List[str]]) -> List[List[str]]:
    """Compute SCCs using an iterative version of Tarjan's algorithm.

    The classic recursive formulation hits Python's default recursion limit
    on graphs with long chains (>1 000 nodes).  This iterative version uses
    an explicit call stack to avoid that.

    Parameters
    ----------
    adj : dict[str, list[str]]
        Adjacency list mapping each node to its successors.

    Returns
    -------
    list[list[str]]
        Each inner list is one strongly connected component.
    """
    index_counter = 0
    stack = []
    indices = {}
    lowlinks = {}
    on_stack = set()
    sccs = []

    for root in adj:
        if root in indices:
            continue
        # Each frame: (node, iterator_over_successors, phase)
        # phase=False means we haven't initialised this node yet.
        call_stack = [(root, iter(adj.get(root, [])), False)]
        while call_stack:
            v, children, initialised = call_stack[-1]
            if not initialised:
                indices[v] = index_counter
                lowlinks[v] = index_counter
                index_counter += 1
                stack.append(v)
                on_stack.add(v)
                call_stack[-1] = (v, children, True)
            # Advance to the next child
            recurse = False
            for w in children:
                if w not in indices:
                    call_stack.append((w, iter(adj.get(w, [])), False))
                    recurse = True
                    break
                elif w in on_stack:
                    lowlinks[v] = min(lowlinks[v], indices[w])
            if recurse:
                continue
            # All children processed — equivalent to returning from strongconnect
            if lowlinks[v] == indices[v]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == v:
                        break
                sccs.append(scc)
            call_stack.pop()
            if call_stack:
                parent = call_stack[-1][0]
                lowlinks[parent] = min(lowlinks[parent], lowlinks[v])

    return sccs


# =========================================================================
# Source file collection
# =========================================================================

def collect_source_files(directory: str, lang_flags: Dict[str, bool]) -> List[str]:
    """Walk *directory* and return a list of source file paths to parse.

    *lang_flags* is a dict of ``show_*`` booleans produced by
    ``_extract_lang_flags`` or ``parse_filters``.
    """
    # Build the set of directories to skip based on active languages.
    skip_dirs = set()
    for flag, dirs in LANG_SKIP_DIRS.items():
        if lang_flags.get(flag):
            skip_dirs.update(dirs)

    result = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)
                   and d not in skip_dirs]
        for fname in files:
            if _should_skip_file(fname):
                continue
            if _wanted_extension(fname, lang_flags):
                result.append(os.path.join(root, fname))
    return result


# =========================================================================
# Main graph builder
# =========================================================================



def build_graph(
    directory: str,
    *,
    lang_flags: Optional[Dict[str, bool]] = None,
    hide_system: bool = False,
    hide_isolated: bool = False,
    filter_dir: str = "",
    **legacy_kwargs: Any
) -> Dict[str, Any]:
    """Parse source files and return the dependency graph as a dict.

    Returns a dict with keys ``nodes``, ``edges``, ``has_cycles``, ``cycles``,
    ``unused_files``, ``coupling``, and ``depth_warnings``.

    Args:
        directory: Root directory to scan for source files.
        lang_flags: Dict mapping show_* flags to booleans. If None, extracted
                   from legacy_kwargs for backward compatibility. Defaults to
                   {"show_c": True, "show_h": True, "show_cpp": True}.
        hide_system: If True, omit external/system imports from the graph.
        hide_isolated: If True, omit files with no dependencies.
        filter_dir: If set, only include files under this directory.
        **legacy_kwargs: For backward compatibility, accepts individual
                        show_* keyword arguments.
    """
    if lang_flags is None:
        lang_flags = {k: v for k, v in legacy_kwargs.items() if k.startswith('show_')}
        if not lang_flags:
            # Default: C/H/CPP enabled, everything else off
            _DEFAULT_ON_LANGS = {'show_c', 'show_h', 'show_cpp'}
            lang_flags = {flag: flag in _DEFAULT_ON_LANGS
                         for flag, _ in LANG_EXTENSION_TABLE}

    import time as _time
    _t0 = _time.time()

    nodes = []
    edges = []
    node_set = set()

    files_to_parse = collect_source_files(directory, lang_flags)

    enabled_langs = [k[len('show_'):] for k, v in lang_flags.items() if v]
    log.info('Scan started  dir=%s  files=%d  langs=%s',
             directory, len(files_to_parse), ','.join(enabled_langs) or 'none')

    # Build a set of known relative paths for import resolution
    known_files = {os.path.relpath(fp, directory) for fp in files_to_parse}

    # Pre-read go.mod if Go is enabled
    go_module_path = parse_go_mod(directory) if lang_flags.get('show_go') else None

    # Pre-scan C# namespace declarations for accurate resolution
    cs_ns_map, cs_class_map = (
        build_cs_namespace_map(directory, known_files) if lang_flags.get('show_cs') else ({}, {})
    )

    # Pre-scan PHP namespace declarations for accurate resolution
    php_ns_map, php_class_map = (
        build_php_namespace_map(directory, known_files) if lang_flags.get('show_php') else ({}, {})
    )

    # Per-build resolution cache — avoids re-resolving the same import string
    # thousands of times across different source files.
    _cache = ResolutionCache()

    # Build a basename → [relative paths] index for fast C/C++ include resolution
    _c_basename_idx = {}
    for kf in known_files:
        bn = os.path.basename(kf)
        _c_basename_idx.setdefault(bn, []).append(kf)

    def _add_edge(source, target) -> None:
        edges.append({
            "data": {
                "source": source,
                "target": target,
                "color": "#94a3b8",
            }
        })
        if target not in node_set:
            nodes.append({"data": {"id": target, "color": _color_for_path(target)}})
            node_set.add(target)

    # Build dispatch table of language handlers
    _handlers = []

    def _handle_python(content, filename) -> None:
        """Handle Python imports (from and import statements)."""
        content = collapse_py_multiline_imports(content)
        for m in PY_FROM_IMPORT_RE.finditer(content):
            from_path = m.group(1)
            names = m.group(2)
            if from_path and not from_path.replace('.', ''):
                for name in names.split(','):
                    name = name.strip()
                    if not name or name == '*':
                        continue
                    mod = from_path + name
                    cached = _cache.get('py', mod, filename)
                    if cached is None:
                        cached = resolve_py_import(
                            mod, filename, directory, known_files
                        )
                        _cache.put('py', mod, filename, cached)
                    resolved, is_external = cached
                    if hide_system and is_external:
                        continue
                    _add_edge(filename, resolved)
            else:
                cached = _cache.get('py', from_path, filename)
                if cached is None:
                    cached = resolve_py_import(
                        from_path, filename, directory, known_files
                    )
                    _cache.put('py', from_path, filename, cached)
                resolved, is_external = cached
                if hide_system and is_external:
                    continue
                _add_edge(filename, resolved)
        for m in PY_IMPORT_RE.finditer(content):
            for mod in m.group(1).split(','):
                mod = mod.strip()
                if not mod:
                    continue
                cached = _cache.get('py', mod, filename)
                if cached is None:
                    cached = resolve_py_import(
                        mod, filename, directory, known_files
                    )
                    _cache.put('py', mod, filename, cached)
                resolved, is_external = cached
                if hide_system and is_external:
                    continue
                _add_edge(filename, resolved)

    def _handle_java(content, filename) -> None:
        """Handle Java imports."""
        for m in JAVA_IMPORT_RE.finditer(content):
            import_path = m.group(1)
            cached = _cache.get('java', import_path)
            if cached is None:
                cached = resolve_java_import(
                    import_path, directory, known_files
                )
                _cache.put('java', import_path, None, cached)
            for resolved, is_external in cached:
                if hide_system and is_external:
                    continue
                _add_edge(filename, resolved)

    def _handle_go(content, filename) -> None:
        """Handle Go imports."""
        for m in GO_IMPORT_RE.finditer(content):
            if m.group(1) is not None:
                for pm in GO_IMPORT_PATH_RE.finditer(m.group(1)):
                    imp = pm.group(1)
                    cached = _cache.get('go', imp)
                    if cached is None:
                        cached = resolve_go_import(
                            imp, directory, known_files, go_module_path
                        )
                        _cache.put('go', imp, None, cached)
                    resolved, is_external = cached
                    if hide_system and is_external:
                        continue
                    _add_edge(filename, resolved)
            else:
                imp = m.group(2)
                cached = _cache.get('go', imp)
                if cached is None:
                    cached = resolve_go_import(
                        imp, directory, known_files, go_module_path
                    )
                    _cache.put('go', imp, None, cached)
                resolved, is_external = cached
                if hide_system and is_external:
                    continue
                _add_edge(filename, resolved)

    def _handle_rust(content, filename) -> None:
        """Handle Rust modules and use statements."""
        for m in RUST_MOD_RE.finditer(content):
            mod_name = m.group(1)
            cached = _cache.get('rust_mod', mod_name, filename)
            if cached is None:
                cached = resolve_rust_mod(
                    mod_name, filename, directory, known_files
                )
                _cache.put('rust_mod', mod_name, filename, cached)
            resolved, is_external = cached
            _add_edge(filename, resolved)
        for m in RUST_USE_RE.finditer(content):
            use_path = m.group(1).rstrip(':')
            top_crate = use_path.split('::')[0]
            if top_crate in ('crate', 'self', 'super'):
                parts = [p for p in use_path.split('::') if p]
                if parts[0] == 'crate':
                    parts = parts[1:]
                elif parts[0] == 'self':
                    self_dir = os.path.dirname(filename)
                    parts = [self_dir] + parts[1:] if self_dir else parts[1:]
                elif parts[0] == 'super':
                    super_count = 0
                    for p in parts:
                        if p == 'super':
                            super_count += 1
                        else:
                            break
                    base = filename
                    for _ in range(super_count + 1):
                        base = os.path.dirname(base)
                    parts = ([base] if base else []) + parts[super_count:]
                parts = [p for p in parts if p]
                if parts:
                    candidate = os.path.join(*parts) + '.rs'
                    if candidate in known_files:
                        _add_edge(filename, candidate)
                        continue
                    candidate = os.path.join(*parts, 'mod.rs')
                    if candidate in known_files:
                        _add_edge(filename, candidate)
                        continue
            else:
                if hide_system:
                    continue
                _add_edge(filename, top_crate)
        for m in RUST_EXTERN_RE.finditer(content):
            crate_name = m.group(1)
            if hide_system:
                continue
            _add_edge(filename, crate_name)

    def _handle_cs(content, filename) -> None:
        """Handle C# using directives."""
        for m in CS_USING_RE.finditer(content):
            namespace = m.group(1)
            cached = _cache.get('cs', namespace)
            if cached is None:
                cached = resolve_cs_using(
                    namespace, directory, known_files,
                    ns_map=cs_ns_map, class_map=cs_class_map
                )
                _cache.put('cs', namespace, None, cached)
            resolved_list, is_external = cached
            if hide_system and is_external:
                continue
            for resolved in resolved_list:
                if resolved != filename:
                    _add_edge(filename, resolved)

    def _handle_swift(content, filename) -> None:
        """Handle Swift imports."""
        for m in SWIFT_IMPORT_RE.finditer(content):
            module_name = m.group(1)
            cached = _cache.get('swift', module_name, filename)
            if cached is None:
                cached = resolve_swift_import(
                    module_name, filename, directory, known_files
                )
                _cache.put('swift', module_name, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_ruby(content, filename) -> None:
        """Handle Ruby requires (both relative and standard)."""
        for m in RUBY_REQUIRE_RELATIVE_RE.finditer(content):
            req_path = m.group(1)
            cached = _cache.get('ruby_rel', req_path, filename)
            if cached is None:
                cached = resolve_ruby_require(
                    req_path, filename, directory, known_files, relative=True
                )
                _cache.put('ruby_rel', req_path, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)
        for m in RUBY_REQUIRE_RE.finditer(content):
            req_path = m.group(1)
            line_text = content[max(0, content.rfind('\n', 0, m.start())+1):m.end()]
            if 'require_relative' in line_text:
                continue
            cached = _cache.get('ruby', req_path)
            if cached is None:
                cached = resolve_ruby_require(
                    req_path, filename, directory, known_files, relative=False
                )
                _cache.put('ruby', req_path, None, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_kotlin(content, filename) -> None:
        """Handle Kotlin imports."""
        for m in KOTLIN_IMPORT_RE.finditer(content):
            import_path = m.group(1)
            cached = _cache.get('kotlin', import_path)
            if cached is None:
                cached = resolve_kotlin_import(
                    import_path, directory, known_files
                )
                _cache.put('kotlin', import_path, None, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_scala(content, filename) -> None:
        """Handle Scala imports."""
        for m in SCALA_IMPORT_RE.finditer(content):
            import_path = m.group(1)
            cached = _cache.get('scala', import_path)
            if cached is None:
                cached = resolve_scala_import(
                    import_path, directory, known_files
                )
                _cache.put('scala', import_path, None, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_php(content, filename) -> None:
        """Handle PHP use statements and require/include."""
        for m in PHP_USE_RE.finditer(content):
            namespace = m.group(1)
            cached = _cache.get('php_use', namespace)
            if cached is None:
                cached = resolve_php_use(
                    namespace, directory, known_files,
                    ns_map=php_ns_map, class_map=php_class_map
                )
                _cache.put('php_use', namespace, None, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            if resolved != filename:
                _add_edge(filename, resolved)
        for m in PHP_REQUIRE_RE.finditer(content):
            req_path = m.group(1)
            cached = _cache.get('php_req', req_path, filename)
            if cached is None:
                cached = resolve_php_require(
                    req_path, filename, directory, known_files
                )
                _cache.put('php_req', req_path, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_dart(content, filename) -> None:
        """Handle Dart/Flutter imports."""
        for m in DART_IMPORT_RE.finditer(content):
            import_path = m.group(1)
            cached = _cache.get('dart', import_path, filename)
            if cached is None:
                cached = resolve_dart_import(
                    import_path, filename, directory, known_files
                )
                _cache.put('dart', import_path, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_elixir(content, filename) -> None:
        """Handle Elixir module aliases."""
        for m in ELIXIR_ALIAS_RE.finditer(content):
            module_name = m.group(1)
            cached = _cache.get('elixir', module_name, filename)
            if cached is None:
                cached = resolve_elixir_module(
                    module_name, filename, directory, known_files
                )
                _cache.put('elixir', module_name, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_lua(content, filename) -> None:
        """Handle Lua require() statements."""
        for m in LUA_REQUIRE_RE.finditer(content):
            req_path = m.group(1)
            cached = _cache.get('lua', req_path, filename)
            if cached is None:
                cached = resolve_lua_require(
                    req_path, filename, directory, known_files
                )
                _cache.put('lua', req_path, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_zig(content, filename) -> None:
        """Handle Zig @import() statements."""
        for m in ZIG_IMPORT_RE.finditer(content):
            import_path = m.group(1)
            cached = _cache.get('zig', import_path, filename)
            if cached is None:
                cached = resolve_zig_import(
                    import_path, filename, directory, known_files
                )
                _cache.put('zig', import_path, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_haskell(content, filename) -> None:
        """Handle Haskell import statements."""
        for m in HASKELL_IMPORT_RE.finditer(content):
            module_name = m.group(1)
            cached = _cache.get('haskell', module_name, filename)
            if cached is None:
                cached = resolve_haskell_import(
                    module_name, filename, directory, known_files
                )
                _cache.put('haskell', module_name, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_r(content, filename) -> None:
        """Handle R library(), require(), and source() statements."""
        for m in R_LIBRARY_RE.finditer(content):
            pkg_name = m.group(1)
            if pkg_name:
                # library()/require() always refer to packages — external
                if hide_system:
                    continue
                _add_edge(filename, pkg_name)
        for m in R_SOURCE_RE.finditer(content):
            source_path = m.group(1)
            cached = _cache.get('r_source', source_path, filename)
            if cached is None:
                cached = resolve_r_source(
                    source_path, filename, directory, known_files
                )
                _cache.put('r_source', source_path, filename, cached)
            resolved, is_external = cached
            if hide_system and is_external:
                continue
            _add_edge(filename, resolved)

    def _handle_c_cpp_js(content, filename) -> None:
        """Handle C/C++ includes and JS/TS imports (line-by-line)."""
        is_js = filename.endswith(JS_EXTENSIONS)
        for line in content.splitlines():
            if not is_js:
                match = INCLUDE_RE.search(line)
                if not match:
                    continue

                is_system = match.group(1) == '<'
                if hide_system and is_system:
                    continue

                included = match.group(2)
                if _include_target_excluded(included, lang_flags):
                    continue

                # Resolve the include path to an actual project file
                cached = _cache.get('c_include', included, filename)
                if cached is None:
                    resolved = _resolve_c_include(
                        included, filename, known_files, _c_basename_idx
                    )
                    if resolved:
                        cached = (resolved, False)
                    elif is_system:
                        # System header not in project — skip or show as external
                        if hide_system:
                            continue
                        cached = (included, True)
                    else:
                        # Quoted include not found — use raw path as-is
                        cached = (included, False)
                    _cache.put('c_include', included, filename, cached)

                target, is_ext = cached
                if hide_system and is_ext:
                    continue
                _add_edge(filename, target)

            else:
                match = JS_IMPORT_RE.search(line)
                if not match:
                    continue

                raw_path = match.group(1) or match.group(2)
                cached = _cache.get('js', raw_path, filename)
                if cached is None:
                    cached = resolve_js_import(
                        raw_path, filename, directory, known_files
                    )
                    _cache.put('js', raw_path, filename, cached)
                resolved, is_external = cached

                if hide_system and is_external:
                    continue

                _add_edge(filename, resolved)

    # Populate the dispatch table based on enabled languages
    if lang_flags.get('show_py'):
        _handlers.append((PY_EXTENSIONS, _handle_python))
    if lang_flags.get('show_java'):
        _handlers.append((JAVA_EXTENSIONS, _handle_java))
    if lang_flags.get('show_go'):
        _handlers.append((GO_EXTENSIONS, _handle_go))
    if lang_flags.get('show_rust'):
        _handlers.append((RUST_EXTENSIONS, _handle_rust))
    if lang_flags.get('show_cs'):
        _handlers.append((CS_EXTENSIONS, _handle_cs))
    if lang_flags.get('show_swift'):
        _handlers.append((SWIFT_EXTENSIONS, _handle_swift))
    if lang_flags.get('show_ruby'):
        _handlers.append((RUBY_EXTENSIONS, _handle_ruby))
    if lang_flags.get('show_kotlin'):
        _handlers.append((KOTLIN_EXTENSIONS, _handle_kotlin))
    if lang_flags.get('show_scala'):
        _handlers.append((SCALA_EXTENSIONS, _handle_scala))
    if lang_flags.get('show_php'):
        _handlers.append((PHP_EXTENSIONS, _handle_php))
    if lang_flags.get('show_dart'):
        _handlers.append((DART_EXTENSIONS, _handle_dart))
    if lang_flags.get('show_elixir'):
        _handlers.append((ELIXIR_EXTENSIONS, _handle_elixir))
    if lang_flags.get('show_lua'):
        _handlers.append((LUA_EXTENSIONS, _handle_lua))
    if lang_flags.get('show_zig'):
        _handlers.append((ZIG_EXTENSIONS, _handle_zig))
    if lang_flags.get('show_haskell'):
        _handlers.append((HASKELL_EXTENSIONS, _handle_haskell))
    if lang_flags.get('show_r'):
        _handlers.append((R_EXTENSIONS, _handle_r))

    # Build combined C/C++/JS extension tuple
    c_cpp_js_exts = ()
    if lang_flags.get('show_c'):
        c_cpp_js_exts += C_EXTENSIONS
    if lang_flags.get('show_h'):
        c_cpp_js_exts += H_EXTENSIONS
    if lang_flags.get('show_cpp'):
        c_cpp_js_exts += CPP_EXTENSIONS
    if lang_flags.get('show_js'):
        c_cpp_js_exts += JS_EXTENSIONS
    if c_cpp_js_exts:
        _handlers.append((c_cpp_js_exts, _handle_c_cpp_js))

    # Main parsing loop using dispatch table
    _total_files = len(files_to_parse)
    _log_interval = max(200, _total_files // 5)  # progress every ~20%
    for _fi, filepath in enumerate(files_to_parse):
        if _fi > 0 and _fi % _log_interval == 0:
            log.debug('Parsing progress  %d/%d files (%.0f%%)',
                      _fi, _total_files, _fi / _total_files * 100)

        filename = os.path.relpath(filepath, directory)

        if filename not in node_set:
            nodes.append({"data": {"id": filename, "color": _color_for_path(filename)}})
            node_set.add(filename)

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        for ext_tuple, handler in _handlers:
            if filepath.endswith(ext_tuple):
                handler(content, filename)
                break

    _t_parsed = _time.time()
    log.info('Parsing complete  files=%d  nodes=%d  edges=%d  %.2fs',
             _total_files, len(nodes), len(edges), _t_parsed - _t0)

    # --- Transitive reduction ---
    # Remove edge A→C when a path A→B→…→C exists of length ≥ 2.
    # This dramatically declutters the visual graph without losing info.
    _adj_set = {}
    for edge in edges:
        _adj_set.setdefault(edge["data"]["source"], set()).add(edge["data"]["target"])

    _redundant = set()
    for src, direct_targets in _adj_set.items():
        for mid in direct_targets:
            # BFS/DFS from mid — any node reachable from mid that is also
            # a direct target of src is redundant.
            _stack = list(_adj_set.get(mid, []))
            _visited = set()
            while _stack:
                _cur = _stack.pop()
                if _cur in _visited:
                    continue
                _visited.add(_cur)
                if _cur in direct_targets and _cur != mid:
                    _redundant.add((src, _cur))
                _stack.extend(_adj_set.get(_cur, []))

    if _redundant:
        edges = [e for e in edges
                 if (e["data"]["source"], e["data"]["target"]) not in _redundant]
        log.info('Transitive reduction removed %d redundant edges', len(_redundant))

    # --- Cycle detection via SCCs ---
    adj = {node["data"]["id"]: [] for node in nodes}
    for edge in edges:
        adj.setdefault(edge["data"]["source"], []).append(edge["data"]["target"])

    sccs = find_sccs(adj)

    cycle_nodes = set()
    cycles_list = []
    for scc in sccs:
        if len(scc) > 1:
            cycle_nodes.update(scc)
            cycles_list.append(scc)

    scc_lookup = {}
    for scc in sccs:
        if len(scc) > 1:
            for node_id in scc:
                scc_lookup[node_id] = scc

    has_cycle_edges = False
    for edge in edges:
        u = edge["data"]["source"]
        v = edge["data"]["target"]
        if u == v:
            edge["classes"] = "cycle"
            has_cycle_edges = True
            if [u] not in cycles_list:
                cycles_list.append([u])
        elif u in scc_lookup and v in scc_lookup and scc_lookup[u] is scc_lookup[v]:
            edge["classes"] = "cycle"
            has_cycle_edges = True

    # --- Compute in-degrees for node sizing ---
    in_degrees = {node["data"]["id"]: 0 for node in nodes}
    for edge in edges:
        target = edge["data"]["target"]
        if target in in_degrees:
            in_degrees[target] += 1

    total_nodes_for_size = len(nodes)
    for node in nodes:
        node["data"]["size"] = node_size_for_degree(
            in_degrees[node["data"]["id"]], total_nodes_for_size
        )

    # --- Compute out-degrees ---
    out_degrees = {node["data"]["id"]: 0 for node in nodes}
    for edge in edges:
        src = edge["data"]["source"]
        if src in out_degrees:
            out_degrees[src] += 1

    # --- Dependency depth (longest transitive dependency chain) ---
    # Iterative post-order DFS avoids hitting Python's recursion limit on
    # large graphs.  Each stack frame is (node_id, child_index, max_so_far).
    dep_depth = {}
    for start in adj:
        if start in dep_depth:
            continue
        dfs_stack = [(start, 0, 0)]
        visiting = {start}
        while dfs_stack:
            node_id, child_idx, max_so_far = dfs_stack[-1]
            children = adj.get(node_id, [])
            advanced = False
            while child_idx < len(children):
                w = children[child_idx]
                child_idx += 1
                if w in visiting:
                    continue  # cycle — skip
                if w in dep_depth:
                    max_so_far = max(max_so_far, 1 + dep_depth[w])
                else:
                    # Save progress and recurse into w
                    dfs_stack[-1] = (node_id, child_idx, max_so_far)
                    dfs_stack.append((w, 0, 0))
                    visiting.add(w)
                    advanced = True
                    break
            if not advanced:
                # All children processed
                dep_depth[node_id] = max_so_far
                visiting.discard(node_id)
                dfs_stack.pop()
                if dfs_stack:
                    pn, pi, pm = dfs_stack[-1]
                    dfs_stack[-1] = (pn, pi, max(pm, 1 + max_so_far))

    for node in nodes:
        node["data"]["depth"] = dep_depth.get(node["data"]["id"], 0)

    # --- Impact analysis (downstream closure size) ---
    rev_adj = {node["data"]["id"]: [] for node in nodes}
    for edge in edges:
        rev_adj.setdefault(edge["data"]["target"], []).append(edge["data"]["source"])

    impact = {}
    def _downstream_closure(node_id) -> int:
        if node_id in impact:
            return impact[node_id]
        visited = set()
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for dep in rev_adj.get(cur, []):
                if dep not in visited and dep != node_id:
                    visited.add(dep)
                    stack.append(dep)
        impact[node_id] = len(visited)
        return impact[node_id]

    for nid in rev_adj:
        _downstream_closure(nid)

    for node in nodes:
        node["data"]["impact"] = impact.get(node["data"]["id"], 0)

    # --- Per-node enrichment: stability, language, degrees, cycle flag ---
    total_nodes = len(nodes)
    for node in nodes:
        nid = node["data"]["id"]
        nd = node["data"]
        ca = in_degrees.get(nid, 0)   # afferent (inbound)
        ce = out_degrees.get(nid, 0)  # efferent (outbound)
        nd["stability"] = round(ce / (ca + ce), 3) if (ca + ce) > 0 else 0.5
        nd["in_degree"] = ca
        nd["out_degree"] = ce
        nd["language"] = _lang_for_path(nid)
        nd["in_cycle"] = nid in cycle_nodes

    # --- Risk classification & sizing (second pass, needs reach_pct) ---
    # reach_pct is computed later, so we do a preliminary pass here and
    # a final risk pass after reach_pct is set (see below).

    # --- Unused file detection (zero inbound edges) ---
    unused_files = [nid for nid, deg in in_degrees.items() if deg == 0]

    # --- Coupling score between directories ---
    dir_edges = {}  # (dirA, dirB) → count
    dir_total = {}  # dir → total edges touching it
    for edge in edges:
        src_dir = os.path.dirname(edge["data"]["source"]) or "."
        tgt_dir = os.path.dirname(edge["data"]["target"]) or "."
        if src_dir != tgt_dir:
            pair = tuple(sorted([src_dir, tgt_dir]))
            dir_edges[pair] = dir_edges.get(pair, 0) + 1
        dir_total[src_dir] = dir_total.get(src_dir, 0) + 1
        dir_total[tgt_dir] = dir_total.get(tgt_dir, 0) + 1

    coupling_scores = []
    for (d1, d2), cross_count in sorted(dir_edges.items(),
                                         key=lambda x: x[1], reverse=True)[:20]:
        total = dir_total.get(d1, 0) + dir_total.get(d2, 0)
        score = round(cross_count / total, 3) if total > 0 else 0
        coupling_scores.append({
            "dir1": d1, "dir2": d2,
            "cross_edges": cross_count, "score": score,
        })

    # --- Optional filters ---
    if hide_isolated:
        connected = set()
        for edge in edges:
            connected.add(edge["data"]["source"])
            connected.add(edge["data"]["target"])
        nodes = [n for n in nodes if n["data"]["id"] in connected]

    if filter_dir:
        nodes = [n for n in nodes if n["data"]["id"].startswith(filter_dir)]
        valid_ids = {n["data"]["id"] for n in nodes}
        edges = [e for e in edges if e["data"]["source"] in valid_ids
                 and e["data"]["target"] in valid_ids]

    # --- Dependency depth warnings ---
    total_files = len(nodes) if nodes else 1
    depth_warnings = []
    for node in nodes:
        nd = node["data"]
        file_id = nd["id"]
        file_depth = nd.get("depth", 0)
        file_impact = nd.get("impact", 0)
        reach_pct = round(file_impact / total_files * 100, 1) if total_files > 0 else 0
        nd["reach_pct"] = reach_pct

        severity = None
        reasons = []

        if reach_pct >= 50:
            severity = "critical"
            reasons.append(f"pulls in {reach_pct}% of codebase")
        elif reach_pct >= 30:
            severity = "warning" if severity != "critical" else severity
            reasons.append(f"pulls in {reach_pct}% of codebase")

        if file_depth >= 8:
            severity = "critical"
            reasons.append(f"dependency chain {file_depth} levels deep")
        elif file_depth >= 5:
            if severity != "critical":
                severity = "warning"
            reasons.append(f"dependency chain {file_depth} levels deep")

        if severity:
            depth_warnings.append({
                "file": file_id,
                "severity": severity,
                "depth": file_depth,
                "impact": file_impact,
                "reach_pct": reach_pct,
                "reasons": reasons,
            })

    depth_warnings.sort(key=lambda w: (0 if w["severity"] == "critical" else 1, -w["reach_pct"]))

    # --- Risk classification (final pass, needs reach_pct) ---
    node_data_lookup = {}
    for node in nodes:
        nd = node["data"]
        risk = classify_node_risk(nd, total_files)
        nd["risk"] = risk
        nd["risk_color"] = RISK_COLORS[risk]
        nd["risk_label"] = RISK_LABELS[risk]
        nd["dir_color"] = _dir_color(nd["id"])
        node_data_lookup[nd["id"]] = nd

    # --- Edge weighting (based on target node importance) ---
    import math as _math
    _max_in = max(in_degrees.values()) if in_degrees else 1
    for edge in edges:
        tgt = edge["data"]["target"]
        tgt_data = node_data_lookup.get(tgt, {})
        tgt_in = in_degrees.get(tgt, 0)
        tgt_reach = tgt_data.get("reach_pct", 0)
        # Weight 1-5: blend of in-degree importance and reach
        raw = (tgt_in / max(_max_in, 1)) * 0.6 + (tgt_reach / 100) * 0.4
        edge["data"]["weight"] = round(1 + 4 * min(raw, 1.0), 2)

    _elapsed = _time.time() - _t0
    log.info('Graph complete  nodes=%d  edges=%d  cycles=%d  warnings=%d  '
             'cache_hits=%d  %.2fs',
             len(nodes), len(edges), len(cycles_list),
             len(depth_warnings), _cache.size, _elapsed)

    return {
        "nodes": nodes,
        "edges": edges,
        "has_cycles": has_cycle_edges,
        "cycles": cycles_list,
        "unused_files": unused_files,
        "coupling": coupling_scores,
        "depth_warnings": depth_warnings,
    }


# =========================================================================
# Language detection
# =========================================================================

def detect_languages(directory: str) -> Dict[str, bool]:
    """Scan *directory* for source files and return which language groups exist.

    Returns a dict mapping ``has_*`` keys (one per entry in
    ``LANG_EXTENSION_TABLE``) to booleans.
    """
    # Build flags dict from the table: "show_py" → "has_py"
    flags = {"has_" + flag[len("show_"):]: False
             for flag, _ in LANG_EXTENSION_TABLE}

    # Collect all skip dirs (union of every language's skip set).
    skip_dirs = set()
    for dirs in LANG_SKIP_DIRS.values():
        skip_dirs.update(dirs)

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d) and d not in skip_dirs]
        for fname in files:
            if _should_skip_file(fname):
                continue
            for flag, exts in LANG_EXTENSION_TABLE:
                has_key = "has_" + flag[len("show_"):]
                if not flags[has_key] and fname.endswith(exts):
                    flags[has_key] = True
            if all(flags.values()):
                return flags
    return flags


# Languages that default to *on* when no explicit flags are given (the
# original C/C++/header group).
_DEFAULT_ON_LANGS = frozenset({"show_c", "show_h", "show_cpp"})


def parse_filters(source: Dict[str, Any], detected: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """Extract filter flags from a request args or form dict.

    When *detected* is provided (a dict from ``detect_languages``), the
    ``mode=auto`` value will use the detected languages instead of enabling
    everything blindly.

    The returned dict is ready to be passed to ``build_graph(**result)``.
    """
    def _to_bool(val, default=False) -> bool:
        """Accept bool, str ('true'/'false'), or fallback to default."""
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() == 'true'
        return default

    mode = source.get('mode', '')

    if mode == 'auto' and detected:
        # Map "has_py" → "show_py" for every language in the table.
        lang = {flag: detected.get("has_" + flag[len("show_"):], False)
                for flag, _ in LANG_EXTENSION_TABLE}
    elif mode == 'auto':
        # No detection data — enable everything.
        lang = {flag: True for flag, _ in LANG_EXTENSION_TABLE}
    else:
        # Explicit flags from the request.  The original C/H/CPP default to
        # "true"; all others default to "false".
        lang = {}
        for flag, _ in LANG_EXTENSION_TABLE:
            default = flag in _DEFAULT_ON_LANGS
            lang[flag] = _to_bool(source.get(flag, default), default)

    return {
        "hide_system": _to_bool(source.get('hide_system', False)),
        **lang,
        "hide_isolated": _to_bool(source.get('hide_isolated', False)),
        "filter_dir": source.get('filter_dir', ''),
    }
