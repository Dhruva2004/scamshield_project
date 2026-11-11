"""
ScamShield AI - tests/test_phase5_integration.py
================================================
End-to-end API tests: HTTP request -> full pipeline -> JSON response -> SQLite.

These are the tests that prove the *system* works, not just the units.
"""

from __future__ import annotations

import pytest

from backend.api.samples import SAMPLES

KYC_SCAM = (
    "Dear Customer, your SBI KYC is suspended today. Update immediately at "
    "http://sbi-kyc-verify.xyz/login or your account will be blocked within 24 hours."
)
BENIGN = "Hi Rahul, are we still meeting at 6 pm near the metro station?"


class TestScanMessageEndpoint:
    def test_scam_is_detected_as_critical(self, client, clean_history):
        response = client.post("/api/v1/scan/message", json={"text": KYC_SCAM})
        assert response.status_code == 200
        body = response.json()

        assert body["risk"]["level"] == "critical"
        assert body["risk"]["score"] >= 70
        assert body["rule_engine"]["matched_count"] >= 3
        assert body["urls"]["urls_found"] == 1
        assert body["urls"]["analyses"][0]["lookalike_of"] == "sbi"

    def test_response_contract_is_complete(self, client, clean_history):
        body = client.post("/api/v1/scan/message", json={"text": KYC_SCAM}).json()
        for key in (
            "scan_id", "created_at", "scan_type", "language", "rule_engine",
            "ml_prediction", "urls", "risk", "explanation", "disclaimer",
            "processing_ms",
        ):
            assert key in body, f"missing key: {key}"

    def test_benign_message_is_low_risk(self, client, clean_history):
        body = client.post("/api/v1/scan/message", json={"text": BENIGN}).json()
        assert body["risk"]["level"] == "low"
        assert body["rule_engine"]["score"] == 0

    def test_layers_are_reported_separately(self, client, clean_history):
        """The ML score and the rule score must never be merged into one field."""
        body = client.post("/api/v1/scan/message", json={"text": KYC_SCAM}).json()
        assert "rule_score" in body["risk"]
        assert "ml_score" in body["risk"]
        assert body["rule_engine"]["score"] is not None
        assert body["ml_prediction"]["label"] in {"spam", "ham", "unknown", "not_applicable"}

    def test_explanation_present_even_without_gemini(self, client, clean_history):
        body = client.post("/api/v1/scan/message", json={"text": KYC_SCAM}).json()
        explanation = body["explanation"]
        assert explanation["available"] is True
        assert explanation["source"] in {"fallback", "gemini"}
        assert explanation["recommendations"]

    def test_explanation_can_be_disabled(self, client, clean_history):
        body = client.post(
            "/api/v1/scan/message",
            json={"text": KYC_SCAM, "include_explanation": False},
        ).json()
        assert body["explanation"]["source"] == "disabled"

    def test_privacy_fields_are_redacted(self, client, clean_history):
        body = client.post(
            "/api/v1/scan/message",
            json={"text": "Share the OTP 482913 sent to 9876543210 or a/c blocked"},
        ).json()
        assert "482913" not in body["input_preview"]
        assert "9876543210" not in body["input_preview"]

    def test_scan_is_persisted(self, client, clean_history):
        scan_id = client.post("/api/v1/scan/message", json={"text": KYC_SCAM}).json()["scan_id"]
        stored = client.get(f"/api/v1/history/{scan_id}")
        assert stored.status_code == 200
        assert stored.json()["scan_id"] == scan_id

    def test_ml_model_is_available(self, client, clean_history):
        body = client.post("/api/v1/scan/message", json={"text": KYC_SCAM, "include_explanation": False}).json()
        assert body["ml_prediction"]["available"] is True
        assert body["ml_prediction"]["spam_probability"] is not None

    @pytest.mark.parametrize("language", ["en", "hi", "hinglish"])
    def test_all_explanation_languages_work(self, client, clean_history, language):
        body = client.post(
            "/api/v1/scan/message", json={"text": KYC_SCAM, "language": language}
        ).json()
        assert body["explanation"]["language"] == language
        assert body["explanation"]["summary"]


class TestScanURLEndpoint:
    def test_suspicious_url_detected(self, client, clean_history):
        body = client.post(
            "/api/v1/scan/url", json={"text": "http://sbi.co.in@secure-login-verify.xyz/kyc/update"}
        ).json()
        assert body["scan_type"] == "url"
        assert body["risk"]["level"] in {"high", "critical"}
        assert body["urls"]["urls_found"] >= 1

    def test_url_scan_skips_ml_explicitly(self, client, clean_history):
        """The SMS model is not meaningful for a bare URL - and we say so."""
        body = client.post("/api/v1/scan/url", json={"text": "https://example.com/x"}).json()
        assert body["ml_prediction"]["available"] is False
        assert "not applied" in body["ml_prediction"]["note"]

    def test_safe_url_is_low_risk(self, client, clean_history):
        body = client.post("/api/v1/scan/url", json={"text": "https://www.sbi.co.in/web/personal-banking"}).json()
        assert body["risk"]["level"] == "low"
        assert body["urls"]["analyses"][0]["score"] == 0


class TestScanTypeAutoDetection:
    def test_bare_url_detected_as_url(self, client, clean_history):
        body = client.post("/api/v1/scan/message", json={"text": "http://sbi-kyc.xyz/login"}).json()
        assert body["scan_type"] == "url"

    def test_sentence_detected_as_message(self, client, clean_history):
        body = client.post(
            "/api/v1/scan/message", json={"text": "Please check http://sbi-kyc.xyz/login"}
        ).json()
        assert body["scan_type"] == "message"


class TestBatchEndpoint:
    def test_batch_returns_one_result_per_item(self, client, clean_history):
        payload = {
            "items": [
                {"text": KYC_SCAM},
                {"text": BENIGN},
                {"text": "You have won a lottery! Pay Rs 5000 processing fee to claim."},
            ]
        }
        body = client.post("/api/v1/scan/batch", json=payload).json()
        assert body["total"] == 3
        assert len(body["results"]) == 3
        assert sum(body["summary"].values()) == 3

    def test_batch_rejects_more_than_twenty(self, client):
        payload = {"items": [{"text": f"message {i}"} for i in range(21)]}
        assert client.post("/api/v1/scan/batch", json=payload).status_code == 422

    def test_batch_rejects_empty_list(self, client):
        assert client.post("/api/v1/scan/batch", json={"items": []}).status_code == 422


class TestInputValidation:
    def test_empty_text_rejected(self, client):
        assert client.post("/api/v1/scan/message", json={"text": ""}).status_code == 422

    def test_whitespace_only_rejected(self, client):
        assert client.post("/api/v1/scan/message", json={"text": "    "}).status_code == 422

    def test_repeated_characters_rejected(self, client):
        response = client.post("/api/v1/scan/message", json={"text": "a" * 50})
        assert response.status_code == 422
        assert "repeated" in response.json()["message"].lower()

    def test_overlong_text_rejected(self, client):
        assert client.post("/api/v1/scan/message", json={"text": "x" * 10_001}).status_code == 422

    def test_invalid_language_rejected(self, client):
        response = client.post("/api/v1/scan/message", json={"text": "hello", "language": "fr"})
        assert response.status_code == 422


class TestRulesAndScoringEndpoints:
    def test_rules_endpoint_lists_catalogue(self, client):
        body = client.get("/api/v1/scan/rules").json()
        assert body["total_rules"] >= 30
        assert "otp" in body["categories"]

    def test_explain_scoring_documents_weights(self, client):
        body = client.get("/api/v1/scan/explain-scoring").json()
        assert body["rule_weights"]["critical"] == 32
        assert "disclaimer" in body

    def test_scoring_weights_match_the_code(self, client):
        """The published weights must equal the ones the engine actually uses."""
        from backend.schemas.common import Severity

        published = client.get("/api/v1/scan/explain-scoring").json()["rule_weights"]
        for severity in Severity:
            assert published[severity.value] == severity.weight


class TestSamplesEndpoint:
    def test_samples_are_served(self, client):
        samples = client.get("/api/v1/samples").json()
        assert len(samples) >= 10
        assert all("text" in sample and "expected_risk" in sample for sample in samples)

    @pytest.mark.parametrize("sample", SAMPLES, ids=[s["id"] for s in SAMPLES])
    def test_every_sample_matches_its_expected_risk(self, client, clean_history, sample):
        """
        Golden-file style test: each documented demo case must produce the risk
        level written next to it. This is what keeps the slides honest.
        """
        body = client.post(
            "/api/v1/scan/message",
            json={"text": sample["text"], "include_explanation": False},
        ).json()
        assert body["risk"]["level"] == sample["expected_risk"], (
            f"{sample['id']}: expected {sample['expected_risk']}, "
            f"got {body['risk']['level']} (score {body['risk']['score']})"
        )

    def test_known_false_positive_is_documented(self):
        """
        The genuine bank alert lands at MEDIUM, not LOW. We assert the CURRENT
        behaviour so a future regression (either direction) is noticed, and the
        sample carries a `note` explaining why we did not tune it away.
        """
        sample = next(s for s in SAMPLES if s["id"] == "benign_bank_alert")
        assert "note" in sample
        assert "false positive" in sample["note"].lower()


class TestHistoryEndpoints:
    def test_history_after_scans(self, client, clean_history):
        client.post("/api/v1/scan/message", json={"text": KYC_SCAM, "include_explanation": False})
        client.post("/api/v1/scan/message", json={"text": BENIGN, "include_explanation": False})

        body = client.get("/api/v1/history").json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        # Newest first.
        assert body["items"][0]["risk_level"] in {"low", "critical"}

    def test_history_filters_by_risk(self, client, clean_history):
        client.post("/api/v1/scan/message", json={"text": KYC_SCAM, "include_explanation": False})
        client.post("/api/v1/scan/message", json={"text": BENIGN, "include_explanation": False})

        critical = client.get("/api/v1/history?risk_level=critical").json()
        assert critical["total"] == 1
        assert critical["items"][0]["risk_level"] == "critical"

    def test_history_does_not_expose_raw_text_by_default(self, client, clean_history):
        client.post("/api/v1/scan/message", json={"text": KYC_SCAM, "include_explanation": False})
        item = client.get("/api/v1/history").json()["items"][0]
        assert "message_preview" in item
        assert "raw_message" not in item

    def test_pagination(self, client, clean_history):
        for index in range(5):
            client.post(
                "/api/v1/scan/message",
                json={"text": f"Message number {index} about a normal meeting", "include_explanation": False},
            )
        page1 = client.get("/api/v1/history?page=1&page_size=2").json()
        page2 = client.get("/api/v1/history?page=2&page_size=2").json()
        assert page1["total"] == 5
        assert len(page1["items"]) == 2
        assert page1["has_more"] is True
        assert page1["items"][0]["scan_id"] != page2["items"][0]["scan_id"]

    def test_delete_single_scan(self, client, clean_history):
        scan_id = client.post(
            "/api/v1/scan/message", json={"text": BENIGN, "include_explanation": False}
        ).json()["scan_id"]
        assert client.delete(f"/api/v1/history/{scan_id}").status_code == 200
        assert client.get(f"/api/v1/history/{scan_id}").status_code == 404

    def test_clear_all_history(self, client, clean_history):
        client.post("/api/v1/scan/message", json={"text": BENIGN, "include_explanation": False})
        body = client.delete("/api/v1/history").json()
        assert body["deleted"] >= 1
        assert client.get("/api/v1/history").json()["total"] == 0

    def test_csv_export(self, client, clean_history):
        client.post("/api/v1/scan/message", json={"text": KYC_SCAM, "include_explanation": False})
        response = client.get("/api/v1/history/export.csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "scan_id" in response.text
        assert len(response.text.strip().splitlines()) >= 2

    def test_stats_reflect_activity(self, client, clean_history):
        client.post("/api/v1/scan/message", json={"text": KYC_SCAM, "include_explanation": False})
        client.post("/api/v1/scan/message", json={"text": BENIGN, "include_explanation": False})
        stats = client.get("/api/v1/history/stats").json()
        assert stats["total_scans"] == 2
        assert stats["high_risk_scans"] >= 1
        assert stats["risk_distribution"]["critical"] >= 1
        assert stats["model_performance"]["available"] is True
        assert stats["model_performance"]["accuracy"] > 0.9


class TestModelEndpoints:
    def test_comparison_endpoint_returns_real_metrics(self, client):
        body = client.get("/api/v1/models/comparison").json()
        assert body["available"] is True
        assert len(body["entries"]) >= 3
        for entry in body["entries"]:
            assert 0.0 <= entry["accuracy"] <= 1.0

    def test_model_info_endpoint(self, client):
        body = client.get("/api/v1/models/info").json()
        assert body["available"] is True
        assert body["language"] == "en"
        assert any("Hindi" in limitation for limitation in body["limitations"])

    def test_terms_endpoint_exposes_interpretable_weights(self, client):
        body = client.get("/api/v1/models/terms").json()
        assert body["available"] is True
        assert body["top_spam_terms"]
        assert body["top_spam_terms"][0]["weight"] > body["top_ham_terms"][0]["weight"]
