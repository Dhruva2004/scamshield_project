"""
ScamShield AI - tests/test_phase4_gemini.py
===========================================
Tests for the explanation layer.

We do NOT call the real Gemini API in tests: that would be slow, cost money and
make results non-deterministic. Instead we test:
  * the deterministic fallback (which must always work, in all 3 languages),
  * prompt construction and privacy redaction inside prompts,
  * the JSON-extraction logic that tolerates markdown fences,
  * graceful degradation with a stubbed client (success, failure, bad output).
"""

from __future__ import annotations

import pytest

from backend.schemas.common import Language
from backend.services.gemini_service import (
    GeminiExplainer,
    build_fallback_explanation,
    build_prompt,
    _extract_json,
    _as_string_list,
)

SAMPLE_FINDINGS = [
    {
        "title": "KYC update / suspension claim",
        "category": "kyc",
        "severity": "high",
        "matched_text": ["your kyc is suspended"],
    },
    {
        "title": "Contains a link",
        "category": "link",
        "severity": "low",
        "matched_text": ["http://sbi-kyc.xyz/login"],
    },
]


class TestFallbackExplanations:
    @pytest.mark.parametrize("language", list(Language))
    def test_fallback_works_in_every_language(self, language):
        explanation = build_fallback_explanation(
            language=language, risk_level="critical", risk_score=100, findings=SAMPLE_FINDINGS
        )
        assert explanation.available is True
        assert explanation.source == "fallback"
        assert explanation.summary
        assert len(explanation.recommendations) >= 3
        # The language actually changed.
        if language is not Language.ENGLISH:
            assert explanation.summary != build_fallback_explanation(
                Language.ENGLISH, "critical", 100, SAMPLE_FINDINGS
            ).summary

    def test_hindi_fallback_uses_devanagari(self):
        explanation = build_fallback_explanation(
            Language.HINDI, "high", 60, SAMPLE_FINDINGS
        )
        assert any("\u0900" <= char <= "\u097F" for char in explanation.summary)

    def test_hinglish_fallback_is_latin_script(self):
        explanation = build_fallback_explanation(
            Language.HINGLISH, "high", 60, SAMPLE_FINDINGS
        )
        assert not any("\u0900" <= char <= "\u097F" for char in explanation.summary)
        assert "ScamShield" in explanation.summary

    def test_fallback_lists_the_actual_findings(self):
        explanation = build_fallback_explanation(
            Language.ENGLISH, "high", 60, SAMPLE_FINDINGS
        )
        assert any("KYC" in element for element in explanation.suspicious_elements)

    def test_fallback_never_claims_safety(self):
        explanation = build_fallback_explanation(Language.ENGLISH, "low", 0, [])
        assert "not a guarantee of safety" in explanation.summary.lower()

    def test_fallback_reports_the_error_reason(self):
        explanation = build_fallback_explanation(
            Language.ENGLISH, "low", 0, [], error="GEMINI_API_KEY is not set."
        )
        assert explanation.error == "GEMINI_API_KEY is not set."


class TestPromptConstruction:
    def test_prompt_redacts_personal_data(self):
        prompt = build_prompt(
            verdict={"risk_level": "high", "risk_score": 60},
            findings=SAMPLE_FINDINGS,
            language=Language.ENGLISH,
            message="Call 9876543210 or mail user@example.com, card 4111 1111 1111 1111",
        )
        assert "9876543210" not in prompt
        assert "user@example.com" not in prompt
        assert "4111 1111 1111 1111" not in prompt
        assert "[PHONE]" in prompt and "[EMAIL]" in prompt

    def test_prompt_contains_the_verdict(self):
        prompt = build_prompt(
            {"risk_level": "critical", "risk_score": 95},
            SAMPLE_FINDINGS,
            Language.HINGLISH,
            "test",
        )
        assert "critical" in prompt
        assert "Hinglish" in prompt

    def test_prompt_is_bounded(self):
        prompt = build_prompt({}, [], Language.ENGLISH, "A" * 50_000)
        assert len(prompt) < 20_000


class TestJSONExtraction:
    def test_plain_json(self):
        assert _extract_json('{"summary": "hi"}') == {"summary": "hi"}

    def test_fenced_json(self):
        raw = '```json\n{"summary": "hi"}\n```'
        assert _extract_json(raw) == {"summary": "hi"}

    def test_json_with_surrounding_prose(self):
        raw = 'Here you go:\n{"summary": "hi"}\nHope that helps!'
        assert _extract_json(raw) == {"summary": "hi"}

    def test_invalid_returns_none(self):
        assert _extract_json("not json at all") is None
        assert _extract_json("") is None
        assert _extract_json("[1,2,3]") is None

    def test_string_list_coercion(self):
        assert _as_string_list(["a", "b"]) == ["a", "b"]
        assert _as_string_list("single") == ["single"]
        assert _as_string_list([{"text": "nested"}]) == ["nested"]
        assert _as_string_list(None) == []


class TestGracefulDegradation:
    def test_disabled_returns_fallback(self):
        explainer = GeminiExplainer(api_key="fake", enabled=False)
        result = explainer.explain(
            risk_level="high", risk_score=60, findings=SAMPLE_FINDINGS,
            message="test", language=Language.ENGLISH,
        )
        assert result.source == "fallback"
        assert "disabled" in (result.error or "").lower()

    def test_missing_key_returns_fallback(self):
        explainer = GeminiExplainer(api_key="", enabled=True)
        result = explainer.explain(
            risk_level="high", risk_score=60, findings=SAMPLE_FINDINGS,
            message="test", language=Language.ENGLISH,
        )
        assert result.source == "fallback"
        assert "GEMINI_API_KEY" in (result.error or "")

    def test_api_exception_returns_fallback(self, monkeypatch):
        explainer = GeminiExplainer(api_key="fake-key", enabled=True)

        # Pretend the SDK is present and the call raises.
        monkeypatch.setattr(explainer, "_ensure_client", lambda: object())

        def boom(_prompt):
            raise RuntimeError("quota exceeded")

        monkeypatch.setattr(explainer, "_call_model", boom)
        result = explainer.explain(
            risk_level="high", risk_score=60, findings=SAMPLE_FINDINGS,
            message="test", language=Language.ENGLISH,
        )
        assert result.source == "fallback"
        assert "failed" in (result.error or "").lower()

    def test_unparsable_output_returns_fallback(self, monkeypatch):
        explainer = GeminiExplainer(api_key="fake-key", enabled=True)
        monkeypatch.setattr(explainer, "_ensure_client", lambda: object())
        monkeypatch.setattr(explainer, "_call_model", lambda _p: "I cannot help with that.")
        result = explainer.explain(
            risk_level="high", risk_score=60, findings=SAMPLE_FINDINGS,
            message="test", language=Language.ENGLISH,
        )
        assert result.source == "fallback"

    def test_valid_output_is_used(self, monkeypatch):
        explainer = GeminiExplainer(api_key="fake-key", enabled=True)
        monkeypatch.setattr(explainer, "_ensure_client", lambda: object())
        monkeypatch.setattr(
            explainer,
            "_call_model",
            lambda _p: '{"summary": "Looks like a KYC scam.", '
                       '"suspicious_elements": ["KYC claim"], '
                       '"scam_techniques": ["urgency"], '
                       '"recommendations": ["Do not click", "Call the bank"]}',
        )
        result = explainer.explain(
            risk_level="high", risk_score=60, findings=SAMPLE_FINDINGS,
            message="test", language=Language.ENGLISH,
        )
        assert result.source == "gemini"
        assert result.summary == "Looks like a KYC scam."
        assert result.recommendations == ["Do not click", "Call the bank"]

    def test_missing_required_fields_returns_fallback(self, monkeypatch):
        explainer = GeminiExplainer(api_key="fake-key", enabled=True)
        monkeypatch.setattr(explainer, "_ensure_client", lambda: object())
        monkeypatch.setattr(explainer, "_call_model", lambda _p: '{"summary": "only this"}')
        result = explainer.explain(
            risk_level="high", risk_score=60, findings=SAMPLE_FINDINGS,
            message="test", language=Language.ENGLISH,
        )
        assert result.source == "fallback"
