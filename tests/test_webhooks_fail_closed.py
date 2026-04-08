"""Regression tests for webhook signature fail-closed behavior."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_empty_secret_rejects_in_non_debug(client):
    """With no secret and debug=False, even a valid-looking signature fails."""
    original_secret = settings.github_webhook_secret
    original_debug = settings.debug
    settings.github_webhook_secret = ""
    settings.debug = False
    try:
        body = json.dumps({"action": "opened"}).encode()
        # Compute a signature with the empty secret — under the old fail-open
        # behavior this would have been accepted.
        resp = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": _sign(body, ""),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
    finally:
        settings.github_webhook_secret = original_secret
        settings.debug = original_debug


def test_empty_secret_allowed_in_debug(client):
    """Debug mode preserves the 'skip verification' escape hatch."""
    original_secret = settings.github_webhook_secret
    original_debug = settings.debug
    settings.github_webhook_secret = ""
    settings.debug = True
    try:
        body = json.dumps({"action": "closed"}).encode()
        resp = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=anything",
                "Content-Type": "application/json",
            },
        )
        # Still ignored because action=closed, but it got past verification.
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
    finally:
        settings.github_webhook_secret = original_secret
        settings.debug = original_debug
