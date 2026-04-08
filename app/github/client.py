"""GitHub API client.

Thin wrapper around the GitHub REST API for the operations PR Impact needs:
  - Cloning repositories (via installation token)
  - Posting / updating PR comments
  - Reading repo config files (.pr-impact.yml)
"""

import base64
import logging
from typing import Optional

import httpx
import yaml

from app.github.auth import get_installation_token

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


async def _headers(installation_id: int) -> dict:
    token = await get_installation_token(installation_id)
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


async def get_clone_token(installation_id: int) -> str:
    """Return an installation token suitable for git clone auth."""
    return await get_installation_token(installation_id)


async def get_repo_config(
    installation_id: int, repo_full_name: str, ref: str
) -> Optional[dict]:
    """Fetch .pr-impact.yml from the repo, if it exists. Returns parsed YAML or None."""
    headers = await _headers(installation_id)
    url = f"{API_BASE}/repos/{repo_full_name}/contents/.pr-impact.yml?ref={ref}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

    data = resp.json()
    raw = data.get("content")
    if not raw:
        logger.warning("No content field in config response for %s", repo_full_name)
        return None

    content = base64.b64decode(raw).decode()
    return yaml.safe_load(content)


async def post_pr_comment(
    installation_id: int, repo_full_name: str, pr_number: int, body: str
) -> int:
    """Post a comment on a PR. Returns the comment ID."""
    headers = await _headers(installation_id)
    url = f"{API_BASE}/repos/{repo_full_name}/issues/{pr_number}/comments"

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json={"body": body})
        resp.raise_for_status()

    comment_id = resp.json()["id"]
    logger.info("Posted comment %d on %s #%d", comment_id, repo_full_name, pr_number)
    return comment_id


async def update_pr_comment(
    installation_id: int, repo_full_name: str, comment_id: int, body: str
):
    """Update an existing PR comment."""
    headers = await _headers(installation_id)
    url = f"{API_BASE}/repos/{repo_full_name}/issues/comments/{comment_id}"

    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, headers=headers, json={"body": body})
        resp.raise_for_status()


async def find_bot_comment(
    installation_id: int, repo_full_name: str, pr_number: int
) -> Optional[int]:
    """Find an existing PR Impact comment on the PR.

    Looks for the hidden ``BOT_MARKER`` placed at the top of every rendered
    comment (see ``app.renderer.markdown``). Paginates through the PR's
    issue comments so busy PRs with many comments still match reliably.

    Returns the comment ID, or None if no bot comment exists yet.
    """
    # Local import to avoid a circular dependency (renderer imports pipeline,
    # pipeline imports from this module transitively in some flows).
    from app.renderer.markdown import BOT_MARKER

    headers = await _headers(installation_id)
    url = f"{API_BASE}/repos/{repo_full_name}/issues/{pr_number}/comments"
    page = 1
    per_page = 100

    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                url,
                headers=headers,
                params={"per_page": per_page, "page": page},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                return None

            for comment in batch:
                body = comment.get("body", "") or ""
                if BOT_MARKER in body:
                    return comment["id"]

            if len(batch) < per_page:
                return None
            page += 1
