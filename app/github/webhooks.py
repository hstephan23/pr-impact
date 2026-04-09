"""GitHub webhook receiver.

Handles incoming webhook events from the GitHub App installation.
We only care about pull_request events (opened, synchronize, reopened).
Everything else is acknowledged and ignored.

Security: every request is verified against the webhook secret using
HMAC-SHA256 before processing.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, HTTPException, Header

from app.config import settings
from app.workers.queue import enqueue_analysis

logger = logging.getLogger(__name__)
router = APIRouter()

# Events we act on — all other events get a 200 OK and are ignored.
_PR_ACTIONS = {"opened", "synchronize", "reopened"}


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify the X-Hub-Signature-256 header matches the webhook secret.

    Fails closed: if no secret is configured, webhooks are rejected unless
    the app is running in debug mode. This prevents accidental deployments
    without a secret from accepting forged events.
    """
    if not settings.github_webhook_secret:
        if settings.debug:
            logger.warning(
                "GITHUB_WEBHOOK_SECRET not set — skipping verification (debug mode)"
            )
            return True
        logger.error(
            "GITHUB_WEBHOOK_SECRET is not configured; rejecting webhook in non-debug mode"
        )
        return False

    if not signature:
        return False

    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
):
    body = await request.body()

    if not _verify_signature(body, x_hub_signature_256):
        logger.warning("Webhook signature verification failed from %s", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored", "event": x_github_event}

    payload = await request.json()
    action = payload.get("action", "")

    if action not in _PR_ACTIONS:
        return {"status": "ignored", "action": action}

    pr = payload["pull_request"]
    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    if installation_id is None:
        logger.warning("pull_request event without installation id — ignoring")
        return {"status": "ignored", "reason": "no installation"}

    job = {
        "installation_id": installation_id,
        "repo_full_name": payload["repository"]["full_name"],
        "pr_number": pr["number"],
        "base_ref": pr["base"]["ref"],
        "base_sha": pr["base"]["sha"],
        "head_ref": pr["head"]["ref"],
        "head_sha": pr["head"]["sha"],
        "clone_url": payload["repository"]["clone_url"],
    }

    await enqueue_analysis(job)
    logger.info("Enqueued analysis for %s #%d", job["repo_full_name"], job["pr_number"])

    return {"status": "queued"}
