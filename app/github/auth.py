"""GitHub App authentication.

GitHub Apps authenticate in two steps:
  1. Sign a JWT with the App's private key (valid 10 min).
  2. Exchange the JWT for an installation access token scoped to specific repos.

The installation token is what we use for all API calls (posting comments, cloning
private repos, etc.). Tokens expire after 1 hour but we refresh proactively.

Token cache is backed by Redis so it works across multiple worker processes.
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

import httpx
import jwt
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None

TOKEN_CACHE_PREFIX = "pr-impact:token:"
# Refresh 5 minutes before expiry
TOKEN_REFRESH_BUFFER = 300


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _create_jwt() -> str:
    """Create a short-lived JWT signed with the App's private key."""
    now = int(time.time())
    payload = {
        "iat": now - 60,           # Allow 60s clock skew
        "exp": now + (10 * 60),    # 10 minute expiry
        "iss": str(settings.github_app_id),
    }
    return jwt.encode(payload, settings.github_private_key, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    """Get a fresh installation access token, using Redis cache when possible."""
    # Check Redis cache
    try:
        r = await _get_redis()
        cached = await r.get(f"{TOKEN_CACHE_PREFIX}{installation_id}")
        if cached:
            data = json.loads(cached)
            if time.time() < data["expires_at"] - TOKEN_REFRESH_BUFFER:
                return data["token"]
    except Exception:
        logger.warning("Token cache read failed for installation %d", installation_id)

    # Fetch new token from GitHub
    app_jwt = _create_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    token = data["token"]
    expires_at = _parse_expires_at(data.get("expires_at"))

    # Store in Redis with TTL matching the token lifetime
    ttl = max(int(expires_at - time.time()), 60)
    try:
        r = await _get_redis()
        await r.set(
            f"{TOKEN_CACHE_PREFIX}{installation_id}",
            json.dumps({"token": token, "expires_at": expires_at}),
            ex=ttl,
        )
    except Exception:
        logger.warning("Token cache write failed for installation %d", installation_id)

    return token


def _parse_expires_at(value: str | None) -> float:
    """Parse GitHub's ISO8601 ``expires_at`` into a Unix timestamp.

    Falls back to one hour from now if the value is missing or malformed,
    matching GitHub's historical installation-token TTL.
    """
    if not value:
        return time.time() + 3600
    try:
        # GitHub returns a trailing "Z" for UTC; fromisoformat wants "+00:00".
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        logger.warning("Unexpected expires_at format from GitHub: %r", value)
        return time.time() + 3600
