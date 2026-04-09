"""ARQ worker — processes PR analysis jobs in the background.

Start with:
    arq app.workers.analyzer.WorkerSettings

Includes retry with exponential backoff and dead-letter logging for
permanently failed jobs.
"""

import logging
import time
from datetime import timedelta

from arq import Retry
from arq.connections import RedisSettings

from app.config import settings
from app.analysis.pipeline import analyze_pr
from app.github.client import find_bot_comment, post_pr_comment, update_pr_comment
from app.renderer.markdown import render_comment, render_error, render_no_changes

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
# Backoff delays: 30s, 120s, 300s
RETRY_DELAYS = [30, 120, 300]


async def run_analysis(ctx: dict, job: dict):
    """Worker function — runs the full analysis pipeline and posts a comment.

    Retries transient failures (clone timeouts, GitHub API 5xx) up to
    MAX_RETRIES times with exponential backoff. Permanent failures are
    logged as dead-letter entries and an error comment is posted on the PR.
    """
    start = time.monotonic()
    repo = job["repo_full_name"]
    pr = job["pr_number"]
    installation_id = job["installation_id"]
    attempt = ctx.get("job_try", 1)

    logger.info("Starting analysis for %s #%d (attempt %d/%d)", repo, pr, attempt, MAX_RETRIES + 1)

    try:
        result = await analyze_pr(job)
        elapsed = int((time.monotonic() - start) * 1000)
        result.analysis_time_ms = elapsed

        # Render the comment
        has_changes = (
            result.files_added or result.files_removed or result.files_modified
            or result.blast_radius_total > 0
        )
        body = render_comment(result) if has_changes else render_no_changes()

        await _upsert_comment(installation_id, repo, pr, body)
        logger.info("Posted/updated comment on %s #%d (%dms)", repo, pr, elapsed)

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)

        if attempt <= MAX_RETRIES:
            delay = RETRY_DELAYS[attempt - 1]
            logger.warning(
                "Analysis failed for %s #%d (attempt %d/%d, retrying in %ds): %s",
                repo, pr, attempt, MAX_RETRIES + 1, delay, exc,
            )
            raise Retry(defer=timedelta(seconds=delay))

        # Exhausted all retries — dead-letter log and error comment
        logger.error(
            "DEAD LETTER: Analysis permanently failed for %s #%d after %d attempts (%dms): %s",
            repo, pr, attempt, elapsed, exc,
            exc_info=True,
        )
        # Best-effort: tell the user analysis failed
        try:
            body = render_error(str(exc), job.get("head_sha", ""))
            await _upsert_comment(installation_id, repo, pr, body)
        except Exception:
            logger.exception(
                "Failed to post error comment on %s #%d", repo, pr
            )


async def _upsert_comment(
    installation_id: int, repo: str, pr: int, body: str
) -> None:
    """Post a new comment or update the bot's existing one."""
    existing = await find_bot_comment(installation_id, repo, pr)
    if existing:
        await update_pr_comment(installation_id, repo, existing, body)
    else:
        await post_pr_comment(installation_id, repo, pr, body)


class WorkerSettings:
    """ARQ worker configuration."""
    functions = [run_analysis]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5
    job_timeout = 300  # 5 min max per analysis
    retry_jobs = True
    max_tries = MAX_RETRIES + 1
