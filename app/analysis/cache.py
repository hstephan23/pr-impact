"""Redis-backed cache for dependency graph results.

Caches GraphResult objects keyed by repo + commit SHA so that base branch
graphs don't need to be rebuilt on every PR update. Head branch graphs
are also cached, benefiting stacked PRs that share commits.

Keys:   pr-impact:graph:{repo}:{sha}
TTL:    24 hours (configurable via GRAPH_CACHE_TTL_SECONDS env var)
"""

import json
import logging
import os
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from engine.adapter import GraphResult

logger = logging.getLogger(__name__)

CACHE_TTL = int(os.environ.get("GRAPH_CACHE_TTL_SECONDS", 86400))  # 24h default

_redis: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _cache_key(repo: str, sha: str) -> str:
    return f"pr-impact:graph:{repo}:{sha}"


def _serialize(result: GraphResult) -> str:
    """Serialize a GraphResult to JSON for Redis storage."""
    return json.dumps({
        "nodes": result.nodes,
        "edges": result.edges,
        "cycles": result.cycles,
        "has_cycles": result.has_cycles,
        "unused_files": result.unused_files,
        "coupling": result.coupling,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
    })


def _deserialize(data: str) -> GraphResult:
    """Deserialize a JSON string back into a GraphResult."""
    d = json.loads(data)
    return GraphResult(
        nodes=d["nodes"],
        edges=d["edges"],
        cycles=d["cycles"],
        has_cycles=d["has_cycles"],
        unused_files=d["unused_files"],
        coupling=d["coupling"],
        node_count=d["node_count"],
        edge_count=d["edge_count"],
    )


async def get_cached_graph(repo: str, sha: str) -> Optional[GraphResult]:
    """Look up a cached graph result. Returns None on miss or error."""
    try:
        r = await _get_redis()
        data = await r.get(_cache_key(repo, sha))
        if data is None:
            return None
        logger.info("Cache hit for %s @ %s", repo, sha[:8])
        return _deserialize(data)
    except Exception:
        logger.warning("Graph cache read failed for %s @ %s", repo, sha[:8], exc_info=True)
        return None


async def set_cached_graph(repo: str, sha: str, result: GraphResult) -> None:
    """Store a graph result in cache with TTL."""
    try:
        r = await _get_redis()
        await r.set(_cache_key(repo, sha), _serialize(result), ex=CACHE_TTL)
        logger.info("Cached graph for %s @ %s (ttl=%ds)", repo, sha[:8], CACHE_TTL)
    except Exception:
        logger.warning("Graph cache write failed for %s @ %s", repo, sha[:8], exc_info=True)
