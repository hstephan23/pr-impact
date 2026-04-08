"""Environment configuration.

All secrets and tunables are loaded from environment variables.
See .env.example for the full list.
"""

import logging
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # --- GitHub App credentials ---
    github_app_id: int = 0
    github_private_key: str = ""          # PEM-encoded RSA private key
    github_webhook_secret: str = ""       # Used to verify webhook signatures

    # --- Redis (job queue) ---
    redis_url: str = "redis://localhost:6379"

    # --- Analysis defaults ---
    default_language: str = "auto"
    blast_radius_warn: int = 10
    blast_radius_critical: int = 30
    max_depth_warning: int = 8
    cycle_tolerance: int = 0

    # --- Server ---
    debug: bool = False
    clone_dir: str = "/tmp/pr-impact-clones"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

# Defensive override: if REDIS_URL is set in the environment, use it directly.
# This guards against any pydantic-settings quirks where .env or defaults
# might shadow the real env var on platforms like Railway.
_env_redis = os.environ.get("REDIS_URL")
if _env_redis:
    settings.redis_url = _env_redis


def _redact(url: str) -> str:
    """Redact credentials from a Redis URL for safe logging."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            _, host = rest.rsplit("@", 1)
            return f"{scheme}://***@{host}"
    return url


# Log the resolved Redis URL at import time (with credentials redacted) so
# operators can verify the right value was picked up in deployment logs.
logger.info("REDIS_URL resolved to: %s", _redact(settings.redis_url))
