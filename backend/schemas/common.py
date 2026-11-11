"""
ScamShield AI - backend/schemas/common.py
=========================================
Shared enums and small models used by several endpoints.

Why separate files: schemas are the *API contract*. Keeping them apart from
the implementation means the frontend can rely on stable field names, and
Pydantic validates every request/response for free.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """
    Human-readable risk buckets.

    Inheriting from `str` means the value serialises to plain JSON strings
    ("high"), which is far easier for the Streamlit/React frontend than an int.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric ordering, handy for sorting and threshold comparisons."""
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]


class ScanType(str, Enum):
    """What kind of artifact the user submitted."""

    MESSAGE = "message"
    EMAIL = "email"
    URL = "url"
    AUTO = "auto"          # let the backend guess from the content


class Language(str, Enum):
    """Languages supported by the *explanation* layer (not by the ML model)."""

    ENGLISH = "en"
    HINDI = "hi"
    HINGLISH = "hinglish"

    @property
    def label(self) -> str:
        return {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}[self.value]


class Severity(str, Enum):
    """Severity of a single triggered detection rule."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        """
        Points contributed to the rule-based score.

        These numbers are the single source of truth and are published by
        GET /api/v1/scan/explain-scoring, so the UI and the docs cannot drift.
        """
        return {"info": 0, "low": 6, "medium": 12, "high": 20, "critical": 32}[self.value]


class ModelInfo(BaseModel):
    """Metadata describing the ML artefact that produced a prediction."""

    name: str = Field(..., description="Algorithm, e.g. 'LogisticRegression'")
    version: str = Field(..., description="Artefact version, e.g. '1.0.0'")
    available: bool = Field(..., description="False when the model failed to load")


class ErrorResponse(BaseModel):
    """Shape of every JSON error returned by the API."""

    error: str
    message: str
    request_id: Optional[str] = None
    details: Optional[object] = None
