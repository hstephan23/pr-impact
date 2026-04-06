"""Environment configuration.

All secrets and tunables are loaded from environment variables.
See .env.example for the full list.
"""

from pydantic_settings import BaseSettings


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

    model_config = {"env_file": ".env", "env_prefix": ""}


settings = Settings()
