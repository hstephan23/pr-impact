"""FastAPI entrypoint for PR Impact.

Exposes:
  POST /webhooks/github  — receives GitHub App webhook events
  GET  /health           — liveness check
"""

from fastapi import FastAPI

from app.config import settings
from app.github.webhooks import router as webhook_router

app = FastAPI(
    title="PR Impact",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
)

app.include_router(webhook_router, prefix="/webhooks")


@app.get("/health")
async def health():
    return {"status": "ok"}
