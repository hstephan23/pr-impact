"""Git churn analysis — extract commit frequency and recency per file.

Runs ``git log`` on the target directory and returns per-file metrics:

* **commits**  — total number of commits that touched the file
* **recent**   — commits in the last 90 days
* **last_date** — ISO date of the most recent commit
* **authors**  — number of distinct committers
* **churn_score** — composite 0-1 score combining frequency, recency & author count

The module is intentionally subprocess-based so it works without any
Python git libraries.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("depgraph.churn")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_churn(directory: str, *, days: int = 365, recent_days: int = 90) -> dict[str, Any]:
    """Return churn data for every tracked file under *directory*.

    Parameters
    ----------
    directory:
        Absolute path to the project root (must be inside a git repo).
    days:
        How far back to look for commits (default 1 year).
    recent_days:
        Window for the "recent commits" counter (default 90 days).

    Returns
    -------
    dict  with keys:
        ``files``   – dict mapping relative path → metrics dict
        ``is_git``  – bool, whether the directory is inside a git repo
        ``period``  – human-readable description of the analysis window
    """
    if not _is_git_repo(directory):
        log.info("Not a git repository: %s", directory)
        return {"files": {}, "is_git": False, "period": ""}

    t0 = time.monotonic()
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)

    # Collect raw per-file commit data from git log
    raw = _git_log_files(directory, since=since_date)

    # Aggregate into per-file metrics
    files: dict[str, dict] = {}
    max_commits = 1
    max_recent = 1
    max_authors = 1

    for rel_path, entries in raw.items():
        commits = len(entries)
        recent = sum(1 for _, d in entries if d >= recent_cutoff)
        authors = len({a for a, _ in entries})
        last_date = max((d for _, d in entries), default=None)

        files[rel_path] = {
            "commits": commits,
            "recent": recent,
            "authors": authors,
            "last_date": last_date.strftime("%Y-%m-%d") if last_date else None,
        }
        max_commits = max(max_commits, commits)
        max_recent = max(max_recent, recent)
        max_authors = max(max_authors, authors)

    # Compute normalised churn_score (0–1)
    for info in files.values():
        freq = info["commits"] / max_commits
        rec = info["recent"] / max_recent
        auth = info["authors"] / max_authors
        # Weighted composite: recency matters most, then frequency, then authors
        info["churn_score"] = round(0.45 * rec + 0.40 * freq + 0.15 * auth, 4)

    elapsed = time.monotonic() - t0
    log.info("Churn analysis complete  files=%d  %.2fs", len(files), elapsed)

    return {
        "files": files,
        "is_git": True,
        "period": f"Last {days} days",
    }


def get_churn_from_remote(git_url: str, *, days: int = 365, recent_days: int = 90) -> dict[str, Any]:
    """Clone a remote git repo (bare) and return churn data.

    Only HTTPS URLs to GitHub, GitLab, and Bitbucket are accepted.
    Uses your local git credentials, so private repos you have access
    to will work.  The clone skips file blobs to save bandwidth.

    Parameters
    ----------
    git_url:
        HTTPS URL of the repo, e.g. ``https://github.com/owner/repo``
        or just ``owner/repo`` (assumes GitHub).
    days, recent_days:
        Same as :func:`get_churn`.

    Returns
    -------
    dict  – same shape as :func:`get_churn`, plus ``"repo"`` key.
    """
    git_url = _normalise_git_url(git_url)
    if git_url is None:
        return {"files": {}, "is_git": False, "period": "", "error": "Invalid repository URL. Use https://github.com/owner/repo or owner/repo."}

    temp_dir = tempfile.mkdtemp(prefix="depgraph_churn_")
    try:
        log.info("Cloning (bare) %s", git_url)
        t0 = time.monotonic()

        # --bare + --filter=blob:none  → get all commits but skip file blobs
        clone_cmd = [
            "git", "clone", "--bare", "--filter=blob:none",
            "--single-branch", git_url, temp_dir,
        ]
        r = subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            err_msg = r.stderr.strip()[:300]
            log.warning("git clone failed: %s", err_msg)
            # Check for common issues
            if "not found" in err_msg.lower() or "404" in err_msg:
                return {"files": {}, "is_git": False, "period": "", "error": "Repository not found. Check the URL and make sure the repo is public."}
            if "authentication" in err_msg.lower() or "403" in err_msg:
                return {"files": {}, "is_git": False, "period": "", "error": "Authentication failed. Check that your git credentials are configured."}
            return {"files": {}, "is_git": False, "period": "", "error": f"Clone failed: {err_msg}"}

        clone_time = time.monotonic() - t0
        log.info("Clone complete in %.1fs", clone_time)

        # For a bare repo, git log works the same way — cwd is the .git dir
        since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
        raw = _git_log_files(temp_dir, since=since_date)

        files: dict[str, dict] = {}
        max_commits = 1
        max_recent = 1
        max_authors = 1

        for rel_path, entries in raw.items():
            commits = len(entries)
            recent = sum(1 for _, d in entries if d >= recent_cutoff)
            authors = len({a for a, _ in entries})
            last_date = max((d for _, d in entries), default=None)

            files[rel_path] = {
                "commits": commits,
                "recent": recent,
                "authors": authors,
                "last_date": last_date.strftime("%Y-%m-%d") if last_date else None,
            }
            max_commits = max(max_commits, commits)
            max_recent = max(max_recent, recent)
            max_authors = max(max_authors, authors)

        for info in files.values():
            freq = info["commits"] / max_commits
            rec = info["recent"] / max_recent
            auth = info["authors"] / max_authors
            info["churn_score"] = round(0.45 * rec + 0.40 * freq + 0.15 * auth, 4)

        elapsed = time.monotonic() - t0
        log.info("Remote churn analysis complete  files=%d  %.2fs", len(files), elapsed)

        return {
            "files": files,
            "is_git": True,
            "period": f"Last {days} days",
            "repo": git_url,
        }

    except subprocess.TimeoutExpired:
        log.warning("git clone timed out for %s", git_url)
        return {"files": {}, "is_git": False, "period": "", "error": "Clone timed out — the repository may be too large."}
    except Exception as exc:
        log.warning("Remote churn failed: %s", exc)
        return {"files": {}, "is_git": False, "period": "", "error": str(exc)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _normalise_git_url(url: str) -> str | None:
    """Validate and normalise a git URL.  Returns None if invalid."""
    url = url.strip()
    # Accept owner/repo shorthand → assume GitHub
    if re.match(r'^[\w.-]+/[\w.-]+$', url):
        return f"https://github.com/{url}.git"
    # Accept full HTTPS URLs to known hosts
    m = re.match(
        r'^https?://(github\.com|gitlab\.com|bitbucket\.org)/([\w./-]+?)(?:\.git)?/?$',
        url, re.IGNORECASE,
    )
    if m:
        host = m.group(1).lower()
        path = m.group(2)
        return f"https://{host}/{path}.git"
    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _is_git_repo(directory: str) -> bool:
    """Check whether *directory* is inside a git work tree."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _git_log_files(
    directory: str, *, since: str
) -> dict[str, list[tuple[str, datetime]]]:
    """Run ``git log`` and return a mapping of relative path → [(author, date), …]."""
    # --name-only gives us file paths after each commit header
    # --format produces a parseable header line per commit
    cmd = [
        "git", "log",
        "--since", since,
        "--format=__COMMIT__%H|%an|%aI",
        "--name-only",
        "--diff-filter=AMRC",   # Added, Modified, Renamed, Copied
        "--no-merges",
    ]

    try:
        r = subprocess.run(
            cmd,
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("git log failed: %s", exc)
        return {}

    if r.returncode != 0:
        log.warning("git log returned %d: %s", r.returncode, r.stderr.strip()[:200])
        return {}

    result: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    current_author: str | None = None
    current_date: datetime | None = None

    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("__COMMIT__"):
            parts = line.split("|", 2)
            if len(parts) >= 3:
                current_author = parts[1]
                try:
                    current_date = datetime.fromisoformat(parts[2])
                except ValueError:
                    current_date = None
        elif current_author and current_date:
            # It's a filename line
            result[line].append((current_author, current_date))

    return dict(result)
