"""FastPilot FastAPI app.

Phase 0: importable skeleton with /health, /metrics, and / so CI's smoke test and
the deployment healthcheck have something real to hit. Phase 1 adds the lifespan
singletons (rag_pipeline, query_router, conversation, semantic_cache), the SSE
streaming endpoints, /feedback, the dogfood logger, and the Opik traces.

Built via an app factory (plan §10.2's testability principle): nothing reads
Settings at import time, so tests can ``get_settings.cache_clear()`` after
monkeypatching env vars and call ``create_app()`` to get a freshly-configured
app — no module reloads needed.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import HealthResponse, MetricsResponse

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the FastAPI app from current settings."""
    settings = get_settings()

    application = FastAPI(title=settings.app_name, version="0.0.0", debug=settings.debug)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/")
    def root() -> dict[str, object]:
        return {
            "name": get_settings().app_name,
            "tagline": "Learn FastAPI, fast.",
            "status": "scaffold",
            "endpoints": ["/health", "/metrics"],
        }

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        # Phase 1 fills component statuses (rag_pipeline / semantic_cache / conversation);
        # the skeleton reports healthy so the deploy healthcheck and CI smoke test pass.
        return HealthResponse(status="healthy", components={"app": "healthy"})

    @application.get("/metrics", response_model=MetricsResponse)
    def metrics() -> MetricsResponse:
        return MetricsResponse()

    return application


# Module-level instance for `uvicorn app.main:app` (Dockerfile / compose / Railway).
app = create_app()
