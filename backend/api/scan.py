"""
ScamShield AI - backend/api/scan.py
===================================
Detection endpoints.

POST /api/v1/scan/message  - analyse a message (auto-detects a bare URL)
POST /api/v1/scan/url      - analyse a URL only (ML intentionally skipped)
POST /api/v1/scan/batch    - analyse up to 20 messages in one call

Every endpoint is thin: validate -> call ScanService -> return. No business
logic lives here, which keeps the router readable and the service testable.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import require_api_key
from backend.core.exceptions import ValidationError
from backend.schemas.common import Language
from backend.schemas.scan import (
    BatchScanRequest,
    BatchScanResponse,
    ScanRequest,
    ScanResponse,
)
from backend.services.risk_assessor import get_risk_assessor
from backend.services.rule_catalog import catalogue_summary
from backend.services.scan_service import get_scan_service, summarise_batch
from backend.services.url_analyzer import get_url_analyzer

router = APIRouter(prefix="/scan", tags=["scan"], dependencies=[Depends(require_api_key)])


def _guard(text: str) -> None:
    """
    Cheap sanity checks before the pipeline runs.

    Pydantic already enforces min/max length; this adds the semantic checks
    that would otherwise produce a confusing empty result.
    """
    if not text or not text.strip():
        raise ValidationError("The message is empty after trimming whitespace.")
    # A wall of one repeated character carries no signal and wastes Gemini quota.
    if len(set(text.strip())) <= 2 and len(text.strip()) > 20:
        raise ValidationError("The message looks like repeated characters, not text.")


@router.post(
    "/message",
    response_model=ScanResponse,
    summary="Analyse a message, email or text containing links",
)
def scan_message(payload: ScanRequest) -> ScanResponse:
    """
    Full three-layer analysis: rules + ML + URL patterns + explanation.

    Example request body:
        {
          "text": "Dear Customer, your SBI KYC is suspended. Update at http://sbi-kyc-verify.xyz/login within 24 hours.",
          "scan_type": "auto",
          "language": "en",
          "include_explanation": true
        }

    Example (trimmed) response:
        {
          "risk": {"level": "critical", "score": 100, "headline": "Do not interact with this message"},
          "rule_engine": {"score": 100, "matched_count": 9},
          "ml_prediction": {"label": "spam", "spam_probability": 0.94},
          "urls": {"urls_found": 1, "highest_score": 67}
        }
    """
    _guard(payload.text)
    return get_scan_service().scan(payload)


@router.post(
    "/url",
    response_model=ScanResponse,
    summary="Analyse a URL with non-invasive pattern checks",
)
def scan_url(
    payload: ScanRequest,
    language: Language = Query(default=Language.ENGLISH, description="Explanation language"),
) -> ScanResponse:
    """
    Analyse a URL. The link is NEVER visited.

    Checks: HTTPS usage, IP-literal hosts, shorteners, punycode/homoglyph
    look-alikes, suspicious TLDs, subdomain depth, brand imitation, phishing
    keywords in the host/path, embedded credentials, unusual ports and
    executable downloads.
    """
    _guard(payload.text)
    return get_scan_service().scan_url_only(
        payload.text, language=payload.language, include_explanation=payload.include_explanation
    )


@router.post(
    "/batch",
    response_model=BatchScanResponse,
    summary="Analyse up to 20 messages in one request",
)
def scan_batch(payload: BatchScanRequest) -> BatchScanResponse:
    """Batch analysis for bulk triage. Each item keeps its own verdict."""
    for item in payload.items:
        _guard(item.text)
    results = get_scan_service().scan_batch(payload)
    return BatchScanResponse(
        results=results, total=len(results), summary=summarise_batch(results)
    )


@router.get("/rules", summary="List every rule in the detection catalogue")
def list_rules() -> Dict[str, Any]:
    """
    Transparency endpoint: the full, human-readable rule catalogue.

    Exposing the rules is a deliberate design choice - a security tool that
    hides its heuristics cannot be audited or trusted.
    """
    rules = catalogue_summary()
    categories: Dict[str, int] = {}
    for rule in rules:
        categories[rule["category"]] = categories.get(rule["category"], 0) + 1
    return {
        "total_rules": len(rules),
        "categories": categories,
        "rules": rules,
        "note": (
            "Rules are deterministic heuristics, not a trained model. Hindi and Hinglish "
            "coverage comes from curated keyword lists."
        ),
    }


@router.get("/explain-scoring", summary="Describe how the risk score is computed")
def explain_scoring() -> Dict[str, Any]:
    """Documentation endpoint for the fusion policy (used by the About page)."""
    return {
        "rule_weights": {"info": 0, "low": 6, "medium": 12, "high": 20, "critical": 32},
        "rule_score_range": "0-100 (capped)",
        "fusion": (
            "final = max(rule_score, ML_component, URL_component) + agreement_bonus. "
            "The ML component is P(spam)*100, capped at 85 and damped when the model "
            "is not confident."
        ),
        "thresholds": {"low": "0-19", "medium": "20-44", "high": "45-69", "critical": "70-100"},
        "disclaimer": (
            "The score is a risk indicator derived from heuristics, not a calibrated "
            "probability that a specific message is fraudulent."
        ),
    }
