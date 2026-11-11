"""
ScamShield AI - backend/api/health.py
=====================================
Liveness/readiness endpoints.

GET /api/v1/health  -> used by the dashboard footer, Docker healthchecks,
                       uptime monitors and the tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from backend.config import get_settings
from backend.database.connection import healthcheck as db_healthcheck
from backend.schemas.history import HealthResponse

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health and configuration summary",
)
def health() -> HealthResponse:
    """
    Report whether the API, database, ML model and Gemini layer are ready.

    Secrets are never returned - only booleans such as `gemini_configured`.
    """
    settings = get_settings()
    db_ok = db_healthcheck()

    # Imported lazily so a missing model file cannot break the health endpoint.
    model_available = settings.active_model_path.exists()

    status_value = "ok" if db_ok else "degraded"

    return HealthResponse(
        status=status_value,
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        model_available=model_available,
        gemini_configured=settings.gemini_available,
        database_backend=settings.database_url.split(":")[0],
        timestamp=datetime.now(timezone.utc),
        components={
            "api": "ok",
            "database": "ok" if db_ok else "error",
            "ml_model": "ok" if model_available else "not_trained",
            "gemini": "configured" if settings.gemini_available else "not_configured",
        },
    )


@router.get("/", include_in_schema=False)
def root() -> dict:
    """Friendly landing payload for people who open the API root in a browser."""
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
        "endpoints": [
            f"{settings.api_prefix}/scan/message",
            f"{settings.api_prefix}/scan/url",
            f"{settings.api_prefix}/history",
            f"{settings.api_prefix}/history/stats",
        ],
    }
