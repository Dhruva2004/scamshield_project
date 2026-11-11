"""
ScamShield AI - tests/test_phase1_foundation.py
===============================================
Phase 1 smoke tests: configuration, database bootstrap, API wiring, error shape.

Run:  pytest tests/test_phase1_foundation.py -v
"""

from __future__ import annotations

import pytest


class TestConfiguration:
    def test_settings_load(self):
        from backend.config import get_settings

        settings = get_settings()
        assert settings.app_name == "ScamShield AI"
        assert settings.api_prefix == "/api/v1"

    def test_cors_origins_parsed_into_list(self):
        from backend.config import get_settings

        origins = get_settings().cors_origin_list
        assert isinstance(origins, list)
        assert any("8501" in origin for origin in origins)

    def test_sqlite_url_is_absolute(self):
        """A relative sqlite:/// URL would break when the cwd changes."""
        from backend.config import get_settings

        settings = get_settings()
        path = settings.sqlite_path
        assert path.endswith(".db")
        assert path.startswith("/"), f"expected absolute sqlite path, got {path}"

    def test_gemini_availability_flag(self):
        """No key -> gemini_available must be False (graceful degradation)."""
        from backend.config import get_settings

        assert get_settings().gemini_available is False

    def test_describe_never_leaks_secrets(self):
        from backend.config import get_settings

        described = get_settings().describe()
        assert "gemini_api_key" not in described
        assert "privacy_salt" not in described


class TestDatabase:
    def test_init_is_idempotent(self):
        from backend.database.connection import init_db

        init_db()
        init_db()  # second call must not raise

    def test_scans_table_exists(self):
        from backend.database.connection import get_connection

        with get_connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scans'"
            ).fetchone()
        assert row is not None

    def test_healthcheck(self):
        from backend.database.connection import healthcheck

        assert healthcheck() is True


class TestPrivacy:
    def test_phone_redacted(self):
        from backend.services.privacy import redact

        assert "[PHONE]" in redact("Call me on 9876543210 now")

    def test_email_redacted(self):
        from backend.services.privacy import redact

        assert "user@example.com" not in redact("mail user@example.com")
        assert "[EMAIL]" in redact("mail user@example.com")

    def test_card_redacted_before_phone(self):
        from backend.services.privacy import redact

        result = redact("card 4111 1111 1111 1111 used")
        assert "[CARD]" in result
        assert "4111" not in result

    def test_otp_value_hidden_but_label_kept(self):
        from backend.services.privacy import redact

        result = redact("Your OTP is 482913")
        assert "482913" not in result
        assert "[OTP]" in result

    def test_hash_is_stable_and_salted(self):
        from backend.services.privacy import content_hash

        assert content_hash("Hello  World") == content_hash("hello world")
        assert content_hash("hello") != content_hash("hello!")

    def test_preview_truncates(self):
        from backend.services.privacy import make_preview

        long_text = "a" * 500
        preview = make_preview(long_text, limit=100)
        assert len(preview) <= 101
        assert preview.endswith("…")
        assert "\n" not in make_preview("line1\nline2")


class TestAPIFoundation:
    def test_health_endpoint(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"ok", "degraded"}
        assert body["components"]["database"] == "ok"
        # No secrets in the health payload.
        assert "gemini_api_key" not in body

    def test_landing_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["name"] == "ScamShield AI"

    def test_request_id_header_present(self, client):
        response = client.get("/api/v1/health")
        assert "X-Request-ID" in response.headers
        assert "X-Process-Time-Ms" in response.headers

    def test_openapi_schema_available(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert "/api/v1/health" in paths
        assert "/api/v1/history" in paths

    def test_history_empty_initially(self, client, clean_history):
        response = client.get("/api/v1/history")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_stats_endpoint_shape(self, client, clean_history):
        response = client.get("/api/v1/history/stats")
        assert response.status_code == 200
        body = response.json()
        for key in ("total_scans", "risk_distribution", "daily_counts", "model_performance"):
            assert key in body

    def test_unknown_scan_returns_404(self, client):
        response = client.get("/api/v1/history/does-not-exist")
        assert response.status_code == 404

    def test_validation_error_is_structured(self, client):
        """Empty text must produce our JSON error envelope, not a stack trace."""
        response = client.post("/api/v1/scan/message", json={"text": "   "})
        assert response.status_code == 422
        body = response.json()
        assert "error" in body and "message" in body and "request_id" in body
