"""Tests for GitHub webhook handling."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


@pytest.fixture
def client():
    return TestClient(app)


def _sign(body: bytes, secret: str) -> str:
    """Create a valid X-Hub-Signature-256 header."""
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_non_pr_event_ignored(client):
    body = json.dumps({"action": "created"}).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": _sign(body, settings.github_webhook_secret),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_pr_closed_ignored(client):
    payload = {
        "action": "closed",
        "pull_request": {"number": 1},
        "installation": {"id": 123},
        "repository": {"full_name": "owner/repo"},
    }
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body, settings.github_webhook_secret),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert resp.json()["action"] == "closed"


def test_invalid_signature_rejected(client):
    body = json.dumps({"action": "opened"}).encode()
    # Temporarily set a webhook secret to enforce verification
    original = settings.github_webhook_secret
    settings.github_webhook_secret = "real-secret"
    try:
        resp = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=invalid",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
    finally:
        settings.github_webhook_secret = original
