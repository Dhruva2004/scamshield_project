"""
ScamShield AI - backend/services/scan_service.py
================================================
The orchestrator: one message in -> one complete ScanResponse out.

Pipeline
--------
    text
     |
     +--> 1. privacy: hash + redact
     +--> 2. rule engine        (explainable, deterministic)
     +--> 3. ML model           (statistical, optional)
     +--> 4. URL analyser       (pattern-based, never visits the link)
     +--> 5. risk assessor      (fuses 2-4 into a verdict)
     +--> 6. explanation layer  (Gemini, optional)
     +--> 7. persist to SQLite  (privacy-respecting)
     |
     v
    ScanResponse

Why an orchestrator instead of fat API endpoints?
-------------------------------------------------
The endpoint should only do HTTP things (parse, validate, return). All business
logic lives here, which means it can be tested with plain function calls, and
the same logic can later serve a CLI, a batch job or a React API without
duplication.

Degradation guarantees
----------------------
* No ML model       -> `ml_prediction.available = False`, scan still succeeds.
* Gemini down/no key -> deterministic fallback explanation.
* Database error     -> scan still returns; persistence failure is logged only.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.config import get_settings
from backend.core.logging_config import get_logger
from backend.database.repositories import scan_repository
from backend.schemas.common import Language, RiskLevel, ScanType
from backend.schemas.scan import BatchScanRequest, ScanRequest, ScanResponse, URLAnalysisResult
from backend.services.gemini_service import get_explainer
from backend.services.model_registry import get_model_registry
from backend.services.privacy import privacy_payload, redact
from backend.services.risk_assessor import get_risk_assessor
from backend.services.rule_engine import get_rule_engine
from backend.services.url_analyzer import get_url_analyzer
from ml.inference.predictor import get_predictor

logger = get_logger(__name__)


class ScanService:
    """Coordinates every detection layer for a single scan."""

    # ------------------------------------------------------------------
    def _detect_type(self, text: str, requested: ScanType) -> ScanType:
        """
        Decide whether the input is a URL or a message when scan_type='auto'.

        A single token that parses as a URL/host is treated as a URL scan;
        anything with spaces or several sentences is a message (which will still
        have its embedded URLs analysed).
        """
        if requested != ScanType.AUTO:
            return requested

        candidate = text.strip()
        if not candidate or any(char.isspace() for char in candidate):
            return ScanType.MESSAGE
        if get_url_analyzer().analyse(candidate).hostname:
            return ScanType.URL
        return ScanType.MESSAGE

    # ------------------------------------------------------------------
    def scan(self, request: ScanRequest, *, persist: bool = True) -> ScanResponse:
        """
        Run the full pipeline for one request.

        Parameters
        ----------
        request : ScanRequest
            Validated user input.
        persist : bool
            When False the result is not written to SQLite (used by tests and
            by the "dry run" mode of the UI).
        """
        started = time.perf_counter()
        settings = get_settings()
        text = request.text

        scan_type = self._detect_type(text, request.scan_type)

        # --- 1. privacy ------------------------------------------------
        privacy = privacy_payload(text)

        # --- 2. rules ---------------------------------------------------
        rule_result = get_rule_engine().analyse(text)

        # --- 3. machine learning ---------------------------------------
        # For a pure URL scan the ML model is not meaningful (it was trained on
        # SMS prose), so we skip it and say so explicitly.
        if scan_type == ScanType.URL:
            from backend.schemas.common import ModelInfo
            from backend.schemas.scan import MLPrediction

            ml_result = MLPrediction(
                available=False,
                label="not_applicable",
                note=(
                    "The ML classifier was trained on SMS text, so it is not applied to "
                    "bare URLs. URL risk comes from the pattern analyser."
                ),
                model=ModelInfo(
                    name="skipped", version="-", available=get_model_registry().is_available
                ),
            )
        else:
            ml_result = get_predictor().predict(text)

        # --- 4. URL analysis -------------------------------------------
        analyses, highest = get_url_analyzer().analyse_text(text)
        url_result = URLAnalysisResult(
            urls_found=len(analyses), analyses=analyses, highest_score=highest
        )

        # --- 5. fused risk ---------------------------------------------
        risk = get_risk_assessor().assess(
            rule_engine=rule_result, ml_prediction=ml_result, urls=url_result
        )

        # --- 6. explanation --------------------------------------------
        if request.include_explanation:
            findings_payload = [
                {
                    "title": finding.title,
                    "category": finding.category,
                    "severity": finding.severity.value,
                    "matched_text": finding.matched_text,
                }
                for finding in rule_result.findings
            ]
            # Add URL findings so the narrative can mention the domain.
            for url_info in analyses[:2]:
                for indicator in url_info.indicators[:3]:
                    findings_payload.append(
                        {
                            "title": indicator.label,
                            "category": "link",
                            "severity": indicator.severity.value,
                            "matched_text": [indicator.detail],
                        }
                    )
            explanation = get_explainer().explain(
                risk_level=risk.level.value,
                risk_score=risk.score,
                findings=findings_payload,
                message=text,
                language=request.language,
            )
        else:
            from backend.schemas.scan import Explanation

            explanation = Explanation(
                available=False,
                source="disabled",
                language=request.language,
                summary="Explanation generation was disabled for this request.",
            )

        processing_ms = int((time.perf_counter() - started) * 1000)
        scan_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc)

        response = ScanResponse(
            scan_id=scan_id,
            created_at=created_at,
            scan_type=scan_type,
            language=request.language,
            input_preview=privacy["message_preview"] or "",
            input_redacted=privacy["message_redacted"] or "",
            rule_engine=rule_result,
            ml_prediction=ml_result,
            urls=url_result,
            risk=risk,
            explanation=explanation,
            processing_ms=processing_ms,
        )

        # --- 7. persistence --------------------------------------------
        if persist:
            self._save(response, privacy, explanation)

        return response

    # ------------------------------------------------------------------
    def _save(self, response: ScanResponse, privacy: Dict[str, Any], explanation) -> None:
        """
        Persist the scan. A database failure must never break the response -
        the user still gets their analysis.
        """
        try:
            scan_repository.save_scan(
                {
                    "scan_id": response.scan_id,
                    "created_at": response.created_at.isoformat(timespec="seconds"),
                    "scan_type": response.scan_type.value,
                    "language": response.language.value,
                    "content_hash": privacy.get("content_hash", ""),
                    "message_preview": privacy.get("message_preview", ""),
                    "message_redacted": privacy.get("message_redacted", ""),
                    "raw_message": privacy.get("raw_message"),
                    "rule_score": response.rule_engine.score,
                    "rule_findings": [
                        {
                            "rule_id": f.rule_id,
                            "title": f.title,
                            "category": f.category,
                            "severity": f.severity.value,
                            "description": f.description,
                            "matched_text": f.matched_text,
                        }
                        for f in response.rule_engine.findings
                    ],
                    "ml_label": response.ml_prediction.label,
                    "ml_spam_probability": response.ml_prediction.spam_probability,
                    "risk_level": response.risk.level.value,
                    "risk_score": response.risk.score,
                    "indicators": [
                        {"title": f.title, "category": f.category}
                        for f in response.rule_engine.findings
                    ]
                    + [
                        {"title": ind.label, "category": "url"}
                        for url_info in response.urls.analyses[:2]
                        for ind in url_info.indicators[:3]
                    ],
                    "summary": response.risk.headline,
                    "explanation": explanation.model_dump(mode="json"),
                    "processing_ms": response.processing_ms,
                }
            )
            # Enforce the retention limit after each write (cheap COUNT query).
            scan_repository.enforce_max_rows(get_settings().history_max_rows)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Could not persist scan %s: %s", response.scan_id, exc)

    # ------------------------------------------------------------------
    def scan_url_only(self, url: str, language: Language, include_explanation: bool = True) -> ScanResponse:
        """Convenience wrapper used by POST /scan/url."""
        return self.scan(
            ScanRequest(text=url, scan_type=ScanType.URL, language=language,
                        include_explanation=include_explanation)
        )

    # ------------------------------------------------------------------
    def scan_batch(self, batch: BatchScanRequest) -> List[ScanResponse]:
        """
        Scan up to 20 messages.

        A failure in one item must not abort the batch, so each item is wrapped
        individually and errors are surfaced as low-confidence results.
        """
        results: List[ScanResponse] = []
        for item in batch.items:
            try:
                results.append(self.scan(item))
            except Exception as exc:
                logger.error("Batch item failed: %s", exc)
                # Re-raise only for programming errors we cannot mask safely.
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                results.append(self._error_response(item, exc))
        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _error_response(request: ScanRequest, exc: Exception) -> ScanResponse:
        """Build a minimal, honest response for a failed batch item."""
        from backend.schemas.scan import (
            Explanation,
            MLPrediction,
            RiskAssessment,
            RuleEngineResult,
            URLAnalysisResult,
        )

        return ScanResponse(
            scan_id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc),
            scan_type=request.scan_type,
            language=request.language,
            input_preview=request.text[:120],
            rule_engine=RuleEngineResult(),
            ml_prediction=MLPrediction(available=False, note="Scan failed."),
            urls=URLAnalysisResult(),
            risk=RiskAssessment(
                level=RiskLevel.LOW,
                score=0,
                rule_score=0,
                headline="Scan could not be completed",
                reasons=[f"Internal error: {type(exc).__name__}"],
                recommended_actions=["Please retry this message."],
            ),
            explanation=Explanation(
                available=False, source="error",
                summary="This item could not be analysed.",
                error=str(exc)[:200],
            ),
        )


scan_service = ScanService()


def get_scan_service() -> ScanService:
    return scan_service


def summarise_batch(results: List[ScanResponse]) -> Dict[str, int]:
    """Count results per risk level, for the batch endpoint."""
    summary = {level.value: 0 for level in RiskLevel}
    for result in results:
        summary[result.risk.level.value] += 1
    return summary
