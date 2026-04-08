"""ARQ worker — processes PR analysis jobs in the background.

Start with:
    arq app.workers.analyzer.WorkerSettings
"""

import logging
import time

from arq.connections import RedisSettings

from app.config import settings
from app.analysis.pipeline import analyze_pr
from app.github.client import find_bot_comment, post_pr_comment, update_pr_comment
from app.renderer.markdown import render_comment, render_error, render_no_changes

logger = logging.getLogger(__name__)


async def run_analysis(ctx: dict, job: dict):
    """Worker function — runs the full analysis pipeline and posts a comment."""
    start = time.monotonic()
    repo = job["repo_full_name"]
    pr = job["pr_number"]
    installation_id = job["installation_id"]

    logger.info("Starting analysis for %s #%d", repo, pr)

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
        logger.exception("Analysis failed for %s #%d", repo, pr)
        # Best-effort: tell the user analysis failed. Swallow secondary
        # errors so ARQ still sees the original failure for retry/backoff.
        try:
            body = render_error(str(exc), job.get("head_sha", ""))
            await _upsert_comment(installation_id, repo, pr, body)
        except Exception:
            logger.exception(
                "Failed to post error comment on %s #%d", repo, pr
            )
        raise


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
