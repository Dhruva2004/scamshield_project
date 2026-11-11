"""
ScamShield AI - tests/test_phase9_deploy.py
===========================================
Tests for the deployment-specific behaviour added for cloud hosting.

These exist because each one corresponds to a way a cloud deploy can break
*silently*: a wrong port, an ephemeral database path, a seed that duplicates
rows, or a missing model artefact. Silent failures are the expensive kind.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# PORT / DATA_DIR handling
# ---------------------------------------------------------------------------
class TestPlatformEnvVars:
    def test_blank_database_url_falls_back_to_data_dir(self, tmp_path, monkeypatch):
        """`DATABASE_URL=` in a .env must not produce an empty URL."""
        monkeypatch.setenv("DATABASE_URL", "")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        import backend.config as config_module

        reloaded = importlib.reload(config_module)
        try:
            settings = reloaded.Settings()
            assert settings.database_url.startswith("sqlite:///")
            assert str(tmp_path) in settings.database_url
            assert settings.sqlite_path.endswith("scamshield.db")
        finally:
            monkeypatch.undo()
            importlib.reload(config_module)

    def test_port_env_var_is_honoured(self, monkeypatch):
        """
        Render/Railway/Fly inject `PORT`; the app must bind to it.

        Uses _env_file=None so a local .env cannot mask the behaviour under test.
        """
        from backend.config import Settings

        monkeypatch.setenv("PORT", "9123")
        assert Settings(_env_file=None).api_port == 9123

    def test_default_port_when_env_missing(self, monkeypatch):
        from backend.config import Settings

        monkeypatch.delenv("PORT", raising=False)
        assert Settings(_env_file=None).api_port == 8000


# ---------------------------------------------------------------------------
# Demo seeding on first boot
# ---------------------------------------------------------------------------
class TestDemoSeeding:
    def test_seeding_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv("SEED_DEMO_DATA", raising=False)
        from backend.main import _maybe_seed_demo_data

        # Must be a no-op: no exception, no rows.
        _maybe_seed_demo_data()

    def test_seeding_skips_when_history_not_empty(self, monkeypatch):
        """
        The dashboard may already hold scans; seeding must not duplicate rows.

        A single real scan is created first so the test does not depend on
        another test having populated the database.
        """
        monkeypatch.setenv("SEED_DEMO_DATA", "true")

        from backend.database.repositories import scan_repository
        from backend.main import _maybe_seed_demo_data
        from backend.schemas.scan import ScanRequest
        from backend.services.scan_service import get_scan_service

        get_scan_service().scan(
            ScanRequest(text="test message for the seeding guard", include_explanation=False)
        )
        before = scan_repository.count_scans()
        assert before > 0

        _maybe_seed_demo_data()
        assert scan_repository.count_scans() == before


# ---------------------------------------------------------------------------
# Deployment artefacts exist and are consistent
# ---------------------------------------------------------------------------
class TestDeployArtefacts:
    def test_render_blueprint_points_at_the_real_health_endpoint(self):
        blueprint = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
        assert "healthCheckPath: /api/v1/health" in blueprint
        assert "dockerfilePath: ./deploy/Dockerfile.api" in blueprint

    def test_render_blueprint_keeps_secrets_out_of_git(self):
        blueprint = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
        # GEMINI_API_KEY and API_KEY must be prompted, never hardcoded.
        for secret in ("GEMINI_API_KEY", "API_KEY"):
            block = blueprint.split(f"key: {secret}")[1].split("- key:")[0]
            assert "sync: false" in block, f"{secret} must not be committed"

    def test_dockerfile_binds_to_platform_port(self):
        dockerfile = (PROJECT_ROOT / "deploy" / "Dockerfile.api").read_text(encoding="utf-8")
        assert "${PORT:-8000}" in dockerfile
        # The old hardcoded 8000 would ignore Render's port and fail the healthcheck.
        assert "--port 8000" not in dockerfile

    def test_dockerfile_ships_the_trained_model(self):
        dockerfile = (PROJECT_ROOT / "deploy" / "Dockerfile.api").read_text(encoding="utf-8")
        assert "COPY models/ ./models/" in dockerfile
        assert "COPY ml/ ./ml/" in dockerfile

    def test_model_artefacts_needed_by_the_image_exist(self):
        for relative in (
            "models/model_logistic_regression.joblib",
            "ml/vectorizers/tfidf_vectorizer.joblib",
            "models/metrics.json",
        ):
            path = PROJECT_ROOT / relative
            assert path.is_file(), f"{relative} missing - the cloud build would lose the ML layer"
            assert path.stat().st_size > 0

    def test_metrics_json_matches_the_shipped_model(self):
        payload = json.loads((PROJECT_ROOT / "models" / "metrics.json").read_text(encoding="utf-8"))
        assert payload["active_model_file"] == "model_logistic_regression.joblib"
        assert 0.0 <= payload["f1"] <= 1.0
        assert len(payload["comparison"]) >= 2, "the brief requires >= 2 compared algorithms"

    def test_export_survives_a_readonly_git_directory(self, tmp_path, monkeypatch):
        """
        Regression test for the Windows failure:

            PermissionError: [WinError 5] Access is denied:
            '...\\dist\\git-export\\.git\\objects\\00\\4d02a9...'

        Git stores objects read-only. The export used to call shutil.rmtree on the
        whole folder, which fails on a read-only file. On Linux the same condition
        is reproduced with chmod 0o444, so this test protects the Windows fix from
        a machine that does not have Windows.
        """
        script = (PROJECT_ROOT / "scripts" / "export_for_git.py").read_text(encoding="utf-8")
        # The read-only aware helpers must exist and be used by build_export.
        assert "def _rmtree_force" in script
        assert "stat.S_IWRITE" in script
        assert "_clear_export_dir()" in script
        assert ".git" in script, "must preserve .git across rebuilds"

        # Exercise the real thing in a throw-away folder.
        import importlib.util

        spec = importlib.util.spec_from_file_location("export_mod", PROJECT_ROOT / "scripts" / "export_for_git.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        fake_export = tmp_path / "git-export"
        (fake_export / ".git" / "objects" / "00").mkdir(parents=True)
        object_file = fake_export / ".git" / "objects" / "00" / "4d02a9"
        object_file.write_text("read-only git object", encoding="utf-8")
        object_file.chmod(0o444)                      # read-only, like Windows
        (fake_export / "stale.txt").write_text("old export content", encoding="utf-8")

        module.EXPORT_DIR = fake_export
        module.build_export()

        assert object_file.exists(), ".git must be preserved"
        assert not (fake_export / "stale.txt").exists(), "stale files must be cleared"
        assert (fake_export / "backend" / "main.py").exists(), "export must be repopulated"

    def test_gitignore_still_blocks_secrets(self):
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert ".env" in ignore
        assert ".streamlit/secrets.toml" in ignore


class TestFrontendSecrets:
    """
    Streamlit Community Cloud has no environment variables - configuration lives in
    the Secrets panel as TOML. These tests cover the two ways that went wrong:

      1. API_BASE_URL in secrets was ignored -> the UI called localhost:8000, which
         on a cloud host is the Streamlit container itself.
      2. API_KEY was read with os.getenv only, so even a correct secrets block
         never sent the header and every call returned 401 once the API had a key.
    """

    @pytest.fixture()
    def with_secrets(self):
        """Populate Streamlit's real Secrets object, then restore it."""
        streamlit = pytest.importorskip("streamlit")
        original = streamlit.secrets._secrets
        def _apply(values: dict) -> None:
            streamlit.secrets._secrets = values
        yield _apply
        streamlit.secrets._secrets = original

    def test_base_url_comes_from_secrets(self, with_secrets, monkeypatch):
        monkeypatch.delenv("API_BASE_URL", raising=False)
        with_secrets({"API_BASE_URL": "https://scamshield-api.onrender.com/"})

        from frontend import api_client

        assert api_client.api_base_url() == "https://scamshield-api.onrender.com"

    def test_api_key_comes_from_secrets(self, with_secrets, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        with_secrets({"API_KEY": "secret-key-value"})

        from frontend import api_client

        assert api_client._headers().get("X-API-Key") == "secret-key-value"

    def test_env_var_is_the_fallback_when_there_are_no_secrets(self, with_secrets, monkeypatch):
        with_secrets({})
        monkeypatch.setenv("API_BASE_URL", "http://127.0.0.1:9000")

        from frontend import api_client

        assert api_client.api_base_url() == "http://127.0.0.1:9000"

    def test_localhost_failure_gives_cloud_specific_advice(self, with_secrets, monkeypatch):
        """
        A localhost URL on a deployed app means the secret is missing. The error
        must say so, instead of telling the user to run uvicorn on a server.
        """
        with_secrets({})
        monkeypatch.delenv("API_BASE_URL", raising=False)

        import requests

        from frontend import api_client

        def boom(*_a, **_k):
            raise requests.exceptions.ConnectionError("refused")

        monkeypatch.setattr(requests, "request", boom)
        with pytest.raises(api_client.APIError) as excinfo:
            api_client.health()
        message = str(excinfo.value)
        assert "Secrets" in message
        assert "localhost" in message


class TestHTTPErrorDiagnosis:
    """
    A 404 is ambiguous: the same status means different things at different URLs.
    The message must therefore always name the URL, and must distinguish "our API
    said no" (JSON) from "something else answered" (HTML).
    """

    def test_html_404_names_the_url_and_blames_the_base_url(self, monkeypatch):
        streamlit = pytest.importorskip("streamlit")
        original = streamlit.secrets._secrets
        streamlit.secrets._secrets = {}
        try:
            import requests

            from frontend import api_client

            class FakeResponse:
                status_code = 404
                text = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN"><h1>Not Found</h1>'

                def json(self):
                    raise ValueError("not json")

            monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse())
            monkeypatch.setenv("API_BASE_URL", "https://wrong-host.example.com")

            with pytest.raises(api_client.APIError) as excinfo:
                api_client.health()

            message = str(excinfo.value)
            assert "https://wrong-host.example.com/api/v1/health" in message
            assert "HTML" in message
            assert "API_BASE_URL" in message
        finally:
            streamlit.secrets._secrets = original

    def test_json_404_does_not_blame_html(self, monkeypatch):
        """Our own API's 404 is JSON and must not be described as an HTML page."""
        streamlit = pytest.importorskip("streamlit")
        original = streamlit.secrets._secrets
        streamlit.secrets._secrets = {}
        try:
            import requests

            from frontend import api_client

            class FakeResponse:
                status_code = 404
                text = '{"detail": "Not Found"}'

                def json(self):
                    return {"detail": "Not Found"}

            monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse())
            monkeypatch.setenv("API_BASE_URL", "https://correct-host.example.com")

            with pytest.raises(api_client.APIError) as excinfo:
                api_client.health()

            message = str(excinfo.value)
            assert "correct-host.example.com/api/v1/health" in message
            assert "not the ScamShield API" not in message
        finally:
            streamlit.secrets._secrets = original

    def test_401_message_mentions_the_api_key(self, monkeypatch):
        streamlit = pytest.importorskip("streamlit")
        original = streamlit.secrets._secrets
        streamlit.secrets._secrets = {}
        try:
            import requests

            from frontend import api_client

            class FakeResponse:
                status_code = 401
                text = '{"detail": "Invalid API key"}'

                def json(self):
                    return {"detail": "Invalid API key"}

            monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse())
            monkeypatch.setenv("API_BASE_URL", "https://api.example.com")

            with pytest.raises(api_client.APIError) as excinfo:
                api_client.health()
            assert "API_KEY" in str(excinfo.value)
        finally:
            streamlit.secrets._secrets = original
