"""
ScamShield AI - backend/core/exceptions.py
==========================================
Domain exceptions + FastAPI exception handlers.

Why: if a service raises `ValueError`, the browser receives an ugly 500 error.
Professional APIs return a *structured* JSON error:

    {
      "error": "validation_error",
      "message": "Message text is empty after cleaning.",
      "request_id": "3f9c..."
    }

`register_exception_handlers(app)` wires that behaviour into FastAPI.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.core.logging_config import get_logger

logger = get_logger(__name__)


class ScamShieldError(Exception):
    """Base class for every error raised by our own services."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "scamshield_error"

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class ValidationError(ScamShieldError):
    """Input is syntactically fine but semantically unusable."""

    # 422 Unprocessable Content. Written numerically because Starlette
    # renamed HTTP_422_UNPROCESSABLE_ENTITY (deprecated alias).
    status_code = 422
    error_code = "validation_error"


class ModelNotLoadedError(ScamShieldError):
    """The ML artefact could not be loaded (not trained yet, corrupt file...)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "model_unavailable"


class UpstreamServiceError(ScamShieldError):
    """An external dependency (Gemini) failed in a way we could not recover."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "upstream_error"


def _error_body(code: str, message: str, request_id: str, details=None) -> dict:
    body = {"error": code, "message": message, "request_id": request_id}
    if details is not None:
        body["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all JSON error handlers to the FastAPI application."""

    @app.exception_handler(ScamShieldError)
    async def _handle_domain_error(request: Request, exc: ScamShieldError):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.warning("[%s] %s: %s", request_id, exc.error_code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.message, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_pydantic_error(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        # exc.errors() may contain non-JSON-serialisable objects -> stringify.
        details = [
            {"loc": list(err.get("loc", [])), "msg": str(err.get("msg", ""))}
            for err in exc.errors()
        ]
        logger.warning("[%s] request validation failed: %s", request_id, details)
        return JSONResponse(
            status_code=422,
            content=_error_body(
                "request_validation_error",
                "One or more request fields are invalid.",
                request_id,
                details,
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        # Log the full traceback server-side, but never leak it to the client.
        logger.exception("[%s] unhandled exception on %s", request_id, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                "internal_error",
                "An unexpected server error occurred. Please try again.",
                request_id,
            ),
        )
