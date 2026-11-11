"""
ScamShield AI - backend/main.py
===============================
FastAPI application entry point.

Run it with:
    uvicorn backend.main:app --reload --port 8000
or:
    python -m backend.main

What happens at start-up
------------------------
1. Logging is configured.
2. The SQLite schema is created (idempotent).
3. The ML model is loaded lazily on first scan, not here - so the API boots
   even before you have trained the model.
4. CORS is configured for the Streamlit frontend.

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend.api import health as health_router
from backend.api import history as history_router
from backend.api import models as models_router
from backend.api import samples as samples_router
from backend.api import scan as scan_router
from backend.config import get_settings
from backend.core.exceptions import register_exception_handlers
from backend.core.logging_config import configure_logging, get_logger
from backend.database.connection import init_db
from backend.services.model_registry import get_model_registry

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


def _maybe_seed_demo_data() -> None:
    """
    Seed 11 real scans on first boot when SEED_DEMO_DATA=true and history is empty.

    Controlled by an environment variable because seeding is a demo convenience,
    not product behaviour: a real deployment should show only real users' scans.
    Any failure here is logged and swallowed - seeding must never stop the API
    from starting.
    """
    import os

    if os.getenv("SEED_DEMO_DATA", "false").strip().lower() not in {"1", "true", "yes"}:
        return

    try:
        from backend.database.repositories import scan_repository

        if scan_repository.count_scans() > 0:
            logger.info("Demo seeding skipped: history is not empty")
            return

        from backend.api.samples import SAMPLES
        from backend.schemas.common import Language
        from backend.schemas.scan import ScanRequest
        from backend.services.scan_service import get_scan_service

        service = get_scan_service()
        created = 0
        for sample in SAMPLES:
            language = (
                Language.HINGLISH if sample["id"] == "hinglish" else Language.ENGLISH
            )
            service.scan(
                ScanRequest(
                    text=sample["text"],
                    language=language,
                    include_explanation=False,   # keep boot time short
                )
            )
            created += 1
        logger.info("Seeded %s demo scan(s) via the real pipeline", created)
    except Exception as exc:  # never fatal
        logger.warning("Demo seeding skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Code that runs on start-up (before) and shutdown (after `yield`)."""
    logger.info("Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.environment)
    init_db()

    # Try to warm the model cache. Failure is logged, never fatal.
    registry = get_model_registry()
    if registry.load() is None:
        logger.warning("Continuing without an ML model - rule-based detection only.")
    else:
        logger.info("ML model ready: %s", registry.metadata().get("model_name", "unknown"))

    # Warm the vectorizer transform path so the first real request is not
    # measurably slower than the rest (matters for p95 latency in production).
    try:
        from ml.inference.predictor import get_predictor

        get_predictor().predict("warmup message for the classifier")
        logger.info("Predictor warm-up complete")
    except Exception as exc:  # never fatal
        logger.warning("Predictor warm-up skipped: %s", exc)

    # Optional, opt-in demo seeding. On a fresh cloud deploy the dashboard would
    # otherwise be empty, which makes a demo or viva look broken. This runs the
    # REAL pipeline over the curated samples - nothing is faked - and only when
    # the table is empty, so it never duplicates rows across restarts.
    _maybe_seed_demo_data()

    logger.info("Docs available at http://localhost:%s/docs", settings.api_port)
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI-powered detection of scam, spam and phishing messages.\n\n"
        "**Layers:** rule-based engine (explainable) + TF-IDF ML classifier "
        "(statistical) + Gemini narrative explanations (optional).\n\n"
        "> ScamShield AI gives guidance, not guarantees. Never share OTPs, "
        "passwords or PINs."
    ),
    contact={"name": "ScamShield AI", "url": "https://github.com/"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    """
    Attach a request id and measure latency for every request.

    The id is echoed in the `X-Request-ID` response header, which makes
    debugging production issues dramatically easier.
    """
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    if not request.url.path.startswith(("/docs", "/openapi.json", "/redoc")):
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    return response


# ---------------------------------------------------------------------------
# Error handlers and routes
# ---------------------------------------------------------------------------
register_exception_handlers(app)

@app.get("/", tags=["system"], summary="API landing page")
def landing() -> dict:
    """Friendly payload for anyone who opens the API root in a browser."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": f"{settings.api_prefix}/health",
        "endpoints": [
            {"method": "POST", "path": f"{settings.api_prefix}/scan/message"},
            {"method": "POST", "path": f"{settings.api_prefix}/scan/url"},
            {"method": "POST", "path": f"{settings.api_prefix}/scan/batch"},
            {"method": "GET", "path": f"{settings.api_prefix}/history"},
            {"method": "GET", "path": f"{settings.api_prefix}/history/stats"},
            {"method": "GET", "path": f"{settings.api_prefix}/models/comparison"},
        ],
        "disclaimer": (
            "Guidance only - ScamShield AI cannot guarantee that a message is "
            "safe or fraudulent. Never share OTPs, passwords or PINs."
        ),
    }


app.include_router(health_router.router, prefix=settings.api_prefix)
app.include_router(scan_router.router, prefix=settings.api_prefix)
app.include_router(history_router.router, prefix=settings.api_prefix)
app.include_router(models_router.router, prefix=settings.api_prefix)
app.include_router(samples_router.router, prefix=settings.api_prefix)


def run() -> None:
    """
    `python -m backend.main` launcher.

    Development : auto-reload, single worker.
    Production  : no reload, multiple workers (WEB_CONCURRENCY, default 2),
                  proxy headers trusted so client IPs are logged correctly.

    In production prefer running uvicorn/gunicorn directly (see deploy/), so
    process supervision is handled by systemd or the container runtime rather
    than by this convenience wrapper.
    """
    import os

    import uvicorn

    if settings.is_production:
        workers = int(os.getenv("WEB_CONCURRENCY", "2"))
        logger.info("Starting in PRODUCTION mode with %s worker(s)", workers)
        uvicorn.run(
            "backend.main:app",
            host=settings.api_host,
            port=settings.api_port,
            workers=workers,
            reload=False,
            proxy_headers=True,
            forwarded_allow_ips="*",
            timeout_keep_alive=30,
            log_level=settings.log_level.lower(),
        )
    else:
        uvicorn.run(
            "backend.main:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=True,
            log_level=settings.log_level.lower(),
        )


if __name__ == "__main__":
    run()
