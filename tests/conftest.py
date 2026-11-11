"""
ScamShield AI - tests/conftest.py
=================================
Shared pytest fixtures.

Why: tests must never touch your real database or .env. The fixtures below
point the app at a throw-away SQLite file and reset cached singletons between
tests so every test starts from a known state.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _isolated_database(tmp_path_factory):
    """
    Force every test session to use a temporary SQLite database.

    This runs BEFORE the app is imported by any test module (autouse, session
    scope) and clears the settings cache if it was already built.
    """
    db_dir = tmp_path_factory.mktemp("db")
    db_file = db_dir / "test_scamshield.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["PRIVACY_SALT"] = "test-salt"
    os.environ["GEMINI_ENABLED"] = "false"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["STORE_RAW_MESSAGE"] = "true"

    from backend import config

    config.get_settings.cache_clear()
    yield db_file

    from backend import config as cfg

    cfg.get_settings.cache_clear()


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient sharing one app instance for the whole session."""
    from fastapi.testclient import TestClient

    from backend.database.connection import init_db
    from backend.main import app

    init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def clean_history():
    """Empty the scans table before/after a test that writes history."""
    from backend.database.connection import init_db
    from backend.database.repositories import scan_repository

    init_db()
    scan_repository.clear_all()
    yield
    scan_repository.clear_all()
