"""Job queue backed by Redis + ARQ.

Webhook handlers enqueue analysis jobs here; the worker process picks them
up and runs the analysis pipeline asynchronously.
"""

import logging

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)

_pool = None


async def _get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def enqueue_analysis(job: dict):
    """Enqueue a PR analysis job for background processing."""
    pool = await _get_pool()
    await pool.enqueue_job("run_analysis", job)
    logger.info("Enqueued job for %s #%d", job["repo_full_name"], job["pr_number"])
