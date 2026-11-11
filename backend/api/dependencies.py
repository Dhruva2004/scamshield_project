"""
ScamShield AI - backend/api/dependencies.py
===========================================
Reusable FastAPI dependencies.

Dependencies are small functions FastAPI calls *before* your endpoint runs.
They are the idiomatic place for:
  * optional API-key protection,
  * resolving services,
  * common validation.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, status

from backend.config import Settings, get_settings


def settings_dependency() -> Settings:
    """Inject the cached settings object into any endpoint."""
    return get_settings()


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """
    Optional shared-secret protection.

    Behaviour:
      * If API_KEY is empty in .env  -> endpoint is public (default for a demo).
      * If API_KEY is set            -> caller must send a matching X-API-Key header.

    This is deliberately simple: for a real deployment use OAuth2/JWT and HTTPS.
    """
    expected = get_settings().api_key.strip()
    if not expected:
        return
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )
