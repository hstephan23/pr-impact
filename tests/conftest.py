"""Shared test fixtures."""

import pytest

# Webhook verification now fails closed when no secret is set. Provide a
# deterministic secret for tests so signed requests can be validated.
from app.config import settings  # noqa: E402

settings.github_webhook_secret = "test-webhook-secret"


@pytest.fixture
def sample_graph():
    """A small dependency graph for testing."""
    return {
        "nodes": [
            {"data": {"id": "src/app.ts"}},
            {"data": {"id": "src/utils/auth.ts"}},
            {"data": {"id": "src/api/client.ts"}},
            {"data": {"id": "src/api/users.ts"}},
            {"data": {"id": "src/pages/profile.tsx"}},
        ],
        "edges": [
            {"data": {"source": "src/app.ts", "target": "src/api/client.ts"}},
            {"data": {"source": "src/api/client.ts", "target": "src/utils/auth.ts"}},
            {"data": {"source": "src/api/users.ts", "target": "src/api/client.ts"}},
            {"data": {"source": "src/pages/profile.tsx", "target": "src/api/users.ts"}},
        ],
    }


@pytest.fixture
def sample_graph_with_cycle():
    """A graph containing a circular dependency."""
    return {
        "nodes": [
            {"data": {"id": "a.ts"}},
            {"data": {"id": "b.ts"}},
            {"data": {"id": "c.ts"}},
        ],
        "edges": [
            {"data": {"source": "a.ts", "target": "b.ts"}},
            {"data": {"source": "b.ts", "target": "c.ts"}},
            {"data": {"source": "c.ts", "target": "a.ts"}},
        ],
    }


@pytest.fixture
def layered_graph():
    """A graph with files in distinct architectural layers."""
    return {
        "nodes": [
            {"data": {"id": "src/ui/Button.tsx"}},
            {"data": {"id": "src/service/userService.ts"}},
            {"data": {"id": "src/data/userCache.ts"}},
            {"data": {"id": "src/util/format.ts"}},
        ],
        "edges": [
            {"data": {"source": "src/ui/Button.tsx", "target": "src/service/userService.ts"}},
            {"data": {"source": "src/service/userService.ts", "target": "src/data/userCache.ts"}},
            {"data": {"source": "src/data/userCache.ts", "target": "src/util/format.ts"}},
            # Violation: data importing from ui
            {"data": {"source": "src/data/userCache.ts", "target": "src/ui/Button.tsx"}},
        ],
    }
