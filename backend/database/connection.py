"""
ScamShield AI - backend/database/connection.py
==============================================
Thin, dependency-free database access layer.

Why not an ORM?
---------------
For an MSc project, raw `sqlite3` keeps the moving parts visible and the
footprint tiny. To stay PostgreSQL-ready we:
  * never build SQL strings with f-strings (always parameterised `?`),
  * keep all SQL inside `repositories.py`,
  * expose only a `get_connection()` contract, so swapping in SQLAlchemy +
    psycopg later only touches this file.

Threading note
--------------
FastAPI runs sync endpoints in a thread pool, so a SQLite connection must not
be shared between threads. We therefore open a *fresh connection per request*
(`check_same_thread=False` plus a short-lived connection), which is the safe
pattern for this workload.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.config import get_settings
from backend.core.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Schema definition (kept as one string so it is easy to audit / migrate)
# ---------------------------------------------------------------------------
SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS scans (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id               TEXT    NOT NULL UNIQUE,
        created_at            TEXT    NOT NULL,              -- ISO-8601 UTC
        scan_type             TEXT    NOT NULL,              -- message | email | url
        language              TEXT    NOT NULL DEFAULT 'en',
        content_hash          TEXT    NOT NULL DEFAULT '',   -- salted SHA-256
        message_preview       TEXT    NOT NULL DEFAULT '',   -- redacted, short
        message_redacted      TEXT    NOT NULL DEFAULT '',   -- redacted, full
        raw_message           TEXT,                          -- NULL if privacy mode
        rule_score            INTEGER NOT NULL DEFAULT 0,
        rule_findings         TEXT    NOT NULL DEFAULT '[]', -- JSON array
        ml_label              TEXT    NOT NULL DEFAULT 'unknown',
        ml_spam_probability   REAL,
        risk_level            TEXT    NOT NULL DEFAULT 'low',
        risk_score            INTEGER NOT NULL DEFAULT 0,
        indicators            TEXT    NOT NULL DEFAULT '[]', -- JSON array
        summary               TEXT    NOT NULL DEFAULT '',
        explanation           TEXT    NOT NULL DEFAULT '',   -- JSON object
        processing_ms         INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_scans_risk_level ON scans(risk_level)",
    "CREATE INDEX IF NOT EXISTS idx_scans_scan_type  ON scans(scan_type)",
    "CREATE INDEX IF NOT EXISTS idx_scans_content_hash ON scans(content_hash)",
]


def _resolve_db_path() -> str:
    """Return the physical SQLite file path, creating its folder if needed."""
    path = get_settings().sqlite_path
    if not path:
        raise RuntimeError(
            "Only SQLite is implemented in this build. "
            "Set DATABASE_URL=sqlite:///./data/scamshield.db"
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db() -> None:
    """
    Create tables and indexes if they do not exist.
    Safe to call on every application start-up (idempotent).
    """
    db_path = _resolve_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")      # better concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()
    logger.info("Database initialised at %s", db_path)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """
    Recreate the schema if the database file was deleted or replaced at runtime.

    Why this exists: an operator (or a cleanup script) can remove the .db file
    while the API is running. Without this check the next query raises
    "no such table: scans" and every stats/history call returns HTTP 500.
    The check costs one indexed read of sqlite_master per connection, which is
    negligible for SQLite, and it makes the service self-healing.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scans'"
    ).fetchone()
    if row is None:
        logger.warning("scans table missing - recreating schema")
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """
    Context manager yielding a configured sqlite3 connection.

        with get_connection() as conn:
            conn.execute("SELECT ...")

    Rows are returned as `sqlite3.Row`, so you can access columns by name
    (`row["risk_level"]`) instead of fragile numeric indexes.
    """
    settings = get_settings()
    conn = sqlite3.connect(_resolve_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        if settings.db_echo:
            conn.set_trace_callback(lambda stmt: logger.debug("SQL: %s", stmt))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def healthcheck() -> bool:
    """Return True when the database answers a trivial query."""
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Database healthcheck failed: %s", exc)
        return False
