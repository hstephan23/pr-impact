"""PR analysis pipeline.

Orchestrates the full analysis flow:
  1. Clone both branches (base and head) into temp directories
  2. Load repo config (.pr-impact.yml) if present
  3. Build dependency graphs for both using the engine
  4. Diff the graphs to find structural changes
  5. Compute blast radius for all changed files
  6. Check architectural violations
  7. Detect new cycles introduced by the PR
  8. Calculate risk score
  9. Return a structured result for comment rendering
"""

import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from app.config import settings
from app.github.client import get_clone_token, get_repo_config
from app.analysis.diff import GraphDiff, diff_graphs
from app.analysis.blast_radius import compute_blast_radius, total_affected
from app.analysis.violations import check_violations
from app.analysis.cycles import diff_cycles
from app.analysis.coupling import diff_couplings
from app.analysis.risk import compute_risk_score
from app.analysis.config import parse_repo_config, config_to_dict
from engine.adapter import scan_directory, to_plain_graph

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Structured output of a PR analysis."""
    repo: str
    pr_number: int
    head_sha: str

    # Changes
    files_added: list[str] = field(default_factory=list)
    files_removed: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    edges_added: list[tuple[str, str]] = field(default_factory=list)
    edges_removed: list[tuple[str, str]] = field(default_factory=list)

    # Impact
    blast_radius: dict[str, list[dict]] = field(default_factory=dict)
    blast_radius_total: int = 0

    # Quality
    new_cycles: list[list[str]] = field(default_factory=list)
    resolved_cycles: list[list[str]] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    coupling_alerts: list[dict] = field(default_factory=list)
    risk_score: int = 0

    # Graph stats
    base_node_count: int = 0
    base_edge_count: int = 0
    head_node_count: int = 0
    head_edge_count: int = 0

    # Metadata
    language: str = "auto"
    analysis_time_ms: int = 0


async def analyze_pr(job: dict) -> AnalysisResult:
    """Run the full analysis pipeline for a PR.

    Args:
        job: Dict with keys: installation_id, repo_full_name, pr_number,
             base_ref, head_ref, head_sha, clone_url

    Returns:
        AnalysisResult with all computed metrics.
    """
    start = time.monotonic()
    installation_id = job["installation_id"]
    repo = job["repo_full_name"]
    clone_url = job["clone_url"]
    pr_number = job["pr_number"]

    # Load and validate repo config from head branch
    raw_config = await get_repo_config(installation_id, repo, job["head_ref"])
    config = parse_repo_config(raw_config)
    config_dict = config_to_dict(config)

    # Clone both branches. For the head we fetch refs/pull/<N>/head, which
    # lives in the base repo and works transparently for fork PRs.
    token = await get_clone_token(installation_id)
    auth_url = clone_url.replace("https://", f"https://x-access-token:{token}@")

    base_dir = tempfile.mkdtemp(prefix="pr-impact-base-")
    head_dir = tempfile.mkdtemp(prefix="pr-impact-head-")

    try:
        _clone_ref(auth_url, job["base_ref"], base_dir)
        _fetch_pr_head(auth_url, pr_number, head_dir)

        # Resolve analysis config from validated config
        paths = config.paths
        language = config.language
        layers = config.layers
        hide_system = config.hide_system
        hide_isolated = config.hide_isolated

        # --- Step 1: Build dependency graphs for both branches ---
        logger.info("Building base graph for %s @ %s", repo, job["base_ref"])
        base_result = scan_directory(
            base_dir,
            language=language,
            hide_system=hide_system,
            hide_isolated=hide_isolated,
            paths=paths,
        )

        logger.info("Building head graph for %s @ %s", repo, job["head_ref"])
        head_result = scan_directory(
            head_dir,
            language=language,
            hide_system=hide_system,
            hide_isolated=hide_isolated,
            paths=paths,
        )

        base_graph = to_plain_graph(base_result)
        head_graph = to_plain_graph(head_result)

        # --- Step 2: Diff the graphs ---
        graph_diff = diff_graphs(base_graph, head_graph)

        if not graph_diff.has_changes:
            logger.info("No structural changes in %s #%d", repo, job["pr_number"])
            return AnalysisResult(
                repo=repo,
                pr_number=job["pr_number"],
                head_sha=job["head_sha"],
                language=language,
                base_node_count=base_result.node_count,
                base_edge_count=base_result.edge_count,
                head_node_count=head_result.node_count,
                head_edge_count=head_result.edge_count,
                analysis_time_ms=int((time.monotonic() - start) * 1000),
            )

        # --- Step 3: Compute blast radius ---
        blast = compute_blast_radius(head_graph, graph_diff.changed_files)
        blast_total = total_affected(blast)

        # --- Step 4: Check architectural violations ---
        violations = check_violations(head_graph, layers) if layers else []

        # --- Step 5: Detect new cycles ---
        new_cycles, resolved_cycles = diff_cycles(
            base_result.cycles, head_result.cycles
        )

        # --- Step 6: Coupling alerts (newly-tight cross-directory coupling) ---
        coupling_alerts = diff_couplings(
            base_result.coupling, head_result.coupling
        )

        # --- Step 7: Determine modified files (in both graphs, edges changed) ---
        base_nodes = {n["data"]["id"] for n in base_graph["nodes"]}
        head_nodes = {n["data"]["id"] for n in head_graph["nodes"]}
        common_files = base_nodes & head_nodes
        modified = sorted(common_files & graph_diff.changed_files)

        # --- Step 8: Risk score ---
        risk = compute_risk_score(
            graph_diff, blast, violations, config_dict, new_cycles=new_cycles
        )

        # --- Build result ---
        elapsed = int((time.monotonic() - start) * 1000)
        return AnalysisResult(
            repo=repo,
            pr_number=job["pr_number"],
            head_sha=job["head_sha"],
            files_added=graph_diff.nodes_added,
            files_removed=graph_diff.nodes_removed,
            files_modified=modified,
            edges_added=graph_diff.edges_added,
            edges_removed=graph_diff.edges_removed,
            blast_radius=blast,
            blast_radius_total=blast_total,
            new_cycles=new_cycles,
            resolved_cycles=resolved_cycles,
            violations=violations,
            coupling_alerts=coupling_alerts,
            risk_score=risk,
            base_node_count=base_result.node_count,
            base_edge_count=base_result.edge_count,
            head_node_count=head_result.node_count,
            head_edge_count=head_result.edge_count,
            language=language,
            analysis_time_ms=elapsed,
        )

    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
        shutil.rmtree(head_dir, ignore_errors=True)


def _clone_ref(url: str, ref: str, dest: str):
    """Shallow-clone a single branch into dest."""
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "--branch", ref, url, dest],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.error("Clone timed out for ref=%s dest=%s", ref, dest)
        raise
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Clone failed for ref=%s: %s",
            ref,
            _scrub(exc.stderr, url),
        )
        raise


def _fetch_pr_head(url: str, pr_number: int, dest: str):
    """Fetch ``refs/pull/<N>/head`` from the base repo into ``dest``.

    This handles both same-repo and fork PRs uniformly because GitHub
    mirrors every PR head under ``refs/pull/<N>/head`` on the base repo.
    """
    def _run(args: list[str], cwd: str | None = None):
        subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            timeout=120,
        )

    try:
        _run(["git", "init", "--quiet", dest])
        _run(["git", "-C", dest, "remote", "add", "origin", url])
        _run([
            "git", "-C", dest, "fetch", "--depth=1", "origin",
            f"pull/{pr_number}/head:refs/pr-impact/head",
        ])
        _run(["git", "-C", dest, "checkout", "--quiet", "refs/pr-impact/head"])
    except subprocess.TimeoutExpired:
        logger.error("PR head fetch timed out for PR #%d dest=%s", pr_number, dest)
        raise
    except subprocess.CalledProcessError as exc:
        logger.error(
            "PR head fetch failed for PR #%d: %s",
            pr_number,
            _scrub(exc.stderr, url),
        )
        raise


def _scrub(data: bytes | None, url: str) -> str:
    """Decode git stderr and redact the installation token from the URL."""
    if not data:
        return "unknown error"
    text = data.decode(errors="replace")
    # Redact the "x-access-token:<token>@" segment if present
    if "x-access-token:" in url:
        scheme, _, rest = url.partition("://")
        if "@" in rest:
            _, _, host = rest.rpartition("@")
            text = text.replace(url, f"{scheme}://***@{host}")
    return text
