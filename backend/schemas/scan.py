"""
ScamShield AI - backend/schemas/scan.py
=======================================
Request / response models for the detection endpoints.

Design rule
-----------
Every layer's output is a SEPARATE field:
  * `rule_engine`     -> explainable, deterministic, human-readable rules
  * `ml_prediction`   -> statistical model opinion + probability
  * `risk`            -> the fused, final verdict
  * `explanation`     -> optional Gemini narrative

We never merge rule hits into the ML probability. A user must always be able
to see *why* the system reached its conclusion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.schemas.common import (
    Language,
    ModelInfo,
    RiskLevel,
    ScanType,
    Severity,
)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class ScanRequest(BaseModel):
    """Body for POST /api/v1/scan/message and /scan/url."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="Message body, email text or URL to analyse.",
        examples=["URGENT: Your SBI KYC is suspended. Click http://sbi-verify.xyz"],
    )
    scan_type: ScanType = Field(
        default=ScanType.AUTO,
        description="Explicit artifact type, or 'auto' to let the server decide.",
    )
    language: Language = Field(
        default=Language.ENGLISH,
        description="Language for the human explanation layer (not the ML model).",
    )
    include_explanation: bool = Field(
        default=True,
        description="Ask Gemini for a narrative explanation (skipped if unavailable).",
    )

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("text must not be empty or whitespace only")
        return value.strip()


# ---------------------------------------------------------------------------
# URL analysis
# ---------------------------------------------------------------------------
class URLIndicator(BaseModel):
    """One specific finding about a URL."""

    code: str = Field(..., description="Machine readable identifier, e.g. 'no_https'")
    label: str = Field(..., description="Short human label")
    detail: str = Field(..., description="One sentence explaining the finding")
    severity: Severity = Severity.INFO


class URLInfo(BaseModel):
    """Structured, non-invasive description of a single URL."""

    raw: str
    normalized: str
    scheme: str = ""
    hostname: str = ""
    registered_domain: str = ""
    tld: str = ""
    path: str = ""
    is_https: bool = False
    is_ip_address: bool = False
    is_shortener: bool = False
    subdomain_count: int = 0
    url_length: int = 0
    suspicious_token_hits: List[str] = Field(default_factory=list)
    lookalike_of: Optional[str] = Field(
        default=None, description="Brand this domain appears to imitate, if any"
    )
    score: int = Field(0, ge=0, le=100, description="URL-only risk score")
    indicators: List[URLIndicator] = Field(default_factory=list)

    @property
    def riskiest(self) -> Optional[URLIndicator]:
        return max(self.indicators, key=lambda i: i.severity.weight, default=None)


class URLAnalysisResult(BaseModel):
    """Result of analysing every URL found in the input."""

    urls_found: int = 0
    analyses: List[URLInfo] = Field(default_factory=list)
    highest_score: int = 0

    @property
    def has_suspicious(self) -> bool:
        return any(u.score >= 40 for u in self.analyses)


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------
class RuleFinding(BaseModel):
    """A single triggered rule."""

    rule_id: str = Field(..., description="Stable id, e.g. 'R_OTP_REQUEST'")
    title: str
    category: str = Field(..., description="otp | urgency | link | payment | ...")
    description: str
    severity: Severity
    matched_text: List[str] = Field(default_factory=list)
    weight: int = Field(..., description="Points this rule contributed")


class RuleEngineResult(BaseModel):
    """Complete, explainable output of the rule-based engine."""

    score: int = Field(0, ge=0, le=100, description="Aggregated rule score (0-100)")
    risk_level: RiskLevel = RiskLevel.LOW
    findings: List[RuleFinding] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    matched_count: int = 0


# ---------------------------------------------------------------------------
# Machine learning
# ---------------------------------------------------------------------------
class MLPrediction(BaseModel):
    """Statistical model opinion, kept strictly separate from rule hits."""

    available: bool = Field(..., description="False when no trained model was found")
    label: str = Field("unknown", description="'spam' | 'ham' | 'unknown'")
    spam_probability: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Model score for the spam class. NOT proof of fraud.",
    )
    threshold: float = 0.5
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    model: Optional[ModelInfo] = None
    note: str = Field(
        "",
        description="Disclaimer explaining how to interpret the probability.",
    )


# ---------------------------------------------------------------------------
# Fused risk
# ---------------------------------------------------------------------------
class RiskAssessment(BaseModel):
    """The final, user-facing verdict."""

    level: RiskLevel
    score: int = Field(..., ge=0, le=100, description="0 = harmless, 100 = near-certain scam")
    rule_score: int = Field(..., ge=0, le=100)
    ml_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    headline: str = Field(..., description="One-line summary")
    reasons: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Explanation layer
# ---------------------------------------------------------------------------
class Explanation(BaseModel):
    """Narrative explanation, normally produced by Gemini."""

    available: bool = False
    source: str = Field("fallback", description="'gemini' | 'fallback' | 'disabled'")
    language: Language = Language.ENGLISH
    summary: str = ""
    suspicious_elements: List[str] = Field(default_factory=list)
    scam_techniques: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    disclaimer: str = ""
    error: Optional[str] = Field(None, description="Why Gemini was not used, if relevant")


# ---------------------------------------------------------------------------
# Full scan response
# ---------------------------------------------------------------------------
class ScanResponse(BaseModel):
    """Everything the UI needs after one scan."""

    scan_id: str
    created_at: datetime
    scan_type: ScanType
    language: Language
    input_preview: str
    input_redacted: str = ""
    rule_engine: RuleEngineResult
    ml_prediction: MLPrediction
    urls: URLAnalysisResult
    risk: RiskAssessment
    explanation: Explanation
    processing_ms: int = 0
    disclaimer: str = (
        "ScamShield AI provides heuristic and statistical guidance only. It cannot "
        "guarantee that a message is safe or fraudulent. Never share OTPs, passwords "
        "or PINs, and verify requests through official channels."
    )


# ---------------------------------------------------------------------------
# Batch scanning
# ---------------------------------------------------------------------------
class BatchScanRequest(BaseModel):
    """Scan several messages in one call (max 20 to keep latency sane)."""

    items: List[ScanRequest] = Field(..., min_length=1, max_length=20)


class BatchScanResponse(BaseModel):
    results: List[ScanResponse]
    total: int
    summary: Dict[str, int] = Field(
        default_factory=dict, description="Count of results per risk level"
    )
