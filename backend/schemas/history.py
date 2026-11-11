"""
ScamShield AI - backend/schemas/history.py
==========================================
Schemas for stored scan history and dashboard statistics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from backend.schemas.common import Language, RiskLevel, ScanType
# Single definition lives in schemas/evaluation.py; imported here so the
# dashboard schema and the model-comparison schema can never drift apart.
from backend.schemas.evaluation import ModelPerformance


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HistoryItem(BaseModel):
    """One stored scan, as returned by GET /api/v1/history."""

    id: int
    scan_id: str
    created_at: datetime
    scan_type: ScanType
    language: Language
    risk_level: RiskLevel
    risk_score: int
    rule_score: int
    ml_label: str
    ml_spam_probability: Optional[float] = None
    message_preview: str = Field(
        "", description="Redacted/truncated preview - never the full raw text by default"
    )
    indicators: List[str] = Field(default_factory=list)
    summary: str = ""


class HistoryDetail(BaseModel):
    """
    Full record of one stored scan.

    `raw_message` is deliberately ABSENT: the detail endpoint only returns the
    redacted text unless the caller explicitly asks for the raw version AND the
    deployment allows storing it (STORE_RAW_MESSAGE=true). This keeps the
    default API surface privacy-preserving.
    """

    id: int
    scan_id: str
    created_at: datetime
    scan_type: ScanType
    language: Language
    risk_level: RiskLevel
    risk_score: int
    rule_score: int
    rule_findings: List[dict] = Field(default_factory=list)
    ml_label: str = "unknown"
    ml_spam_probability: Optional[float] = None
    message_preview: str = ""
    message_redacted: str = ""
    indicators: List[dict] = Field(default_factory=list)
    summary: str = ""
    explanation: dict = Field(default_factory=dict)
    processing_ms: int = 0
    content_hash: str = ""
    raw_message: Optional[str] = Field(
        None, description="Only populated when ?include_raw=true and storage is enabled"
    )


class HistoryPage(BaseModel):
    """Paginated history response."""

    items: List[HistoryItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class ClearHistoryResponse(BaseModel):
    deleted: int
    message: str


class RiskDistribution(BaseModel):
    low: int = 0
    medium: int = 0
    high: int = 0
    critical: int = 0


class DailyCount(BaseModel):
    date: str
    count: int


class StatsResponse(BaseModel):
    """Aggregate numbers powering the dashboard cards and charts."""

    total_scans: int = 0
    spam_detected: int = 0
    suspicious_urls: int = 0
    high_risk_scans: int = 0
    risk_distribution: RiskDistribution = Field(default_factory=RiskDistribution)
    daily_counts: List[DailyCount] = Field(default_factory=list)
    scans_by_type: Dict[str, int] = Field(default_factory=dict)
    top_indicators: List[Dict[str, object]] = Field(default_factory=list)
    average_risk_score: Optional[float] = None
    model_performance: ModelPerformance = Field(default_factory=ModelPerformance)
    generated_at: datetime = Field(default_factory=_utcnow)


class HealthResponse(BaseModel):
    """Response of GET /api/v1/health - used by monitors and the UI footer."""

    status: str = "ok"
    app_name: str
    version: str
    environment: str
    model_available: bool = False
    gemini_configured: bool = False
    database_backend: str = "sqlite"
    timestamp: datetime = Field(default_factory=_utcnow)
    components: Dict[str, str] = Field(default_factory=dict)
