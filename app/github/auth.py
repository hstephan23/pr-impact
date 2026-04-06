"""GitHub App authentication.

GitHub Apps authenticate in two steps:
  1. Sign a JWT with the App's private key (valid 10 min).
  2. Exchange the JWT for an installation access token scoped to specific repos.

The installation token is what we use for all API calls (posting comments, cloning
private repos, etc.). Tokens expire after 1 hour but we refresh proactively.
"""

import time

import jwt
import httpx

from app.config import settings

# Cache installation tokens to avoid re-creating on every request.
_token_cache: dict[int, tuple[str, float]] = {}  # installation_id → (token, expires_at)


def _create_jwt() -> str:
    """Create a short-lived JWT signed with the App's private key."""
    now = int(time.time())
    payload = {
        "iat": now - 60,           # Allow 60s clock skew
        "exp": now + (10 * 60),    # 10 minute expiry
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, settings.github_private_key, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    """Get a fresh installation access token, using cache when possible."""
    cached = _token_cache.get(installation_id)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at - 300:  # Refresh 5 min early
            return token

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
    # GitHub returns expires_at as ISO string; we approximate with 1h from now.
    _token_cache[installation_id] = (token, time.time() + 3600)
    return token
