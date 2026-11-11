"""
ScamShield AI - backend/database/repositories.py
================================================
The ONLY module allowed to write SQL for scan history.

A "repository" is a small class that hides database details behind methods that
speak the language of the domain: save_scan(), list_scans(), get_stats(), ...

This separation means:
  * services stay testable without a database,
  * SQL is reviewed in one place,
  * moving to PostgreSQL means changing only this file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_logger
from backend.database.connection import get_connection

logger = get_logger(__name__)


def _utc_iso() -> str:
    """Timezone-aware ISO-8601 timestamp, stored as TEXT in SQLite."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json_loads(raw: str, fallback: Any) -> Any:
    """Never let a corrupt JSON column crash the API."""
    try:
        return json.loads(raw) if raw else fallback
    except (json.JSONDecodeError, TypeError):
        return fallback


class ScanRepository:
    """CRUD + analytics for the `scans` table."""

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def save_scan(self, record: Dict[str, Any]) -> int:
        """
        Insert one scan. Returns the new row id.

        `record` is produced by ScanService and already respects the privacy
        settings (raw text may be None).
        """
        sql = """
            INSERT INTO scans (
                scan_id, created_at, scan_type, language, content_hash,
                message_preview, message_redacted, raw_message,
                rule_score, rule_findings, ml_label, ml_spam_probability,
                risk_level, risk_score, indicators, summary, explanation,
                processing_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record["scan_id"],
            record.get("created_at", _utc_iso()),
            record.get("scan_type", "message"),
            record.get("language", "en"),
            record.get("content_hash", ""),
            record.get("message_preview", "")[:500],
            record.get("message_redacted", "")[:5000],
            record.get("raw_message"),
            int(record.get("rule_score", 0)),
            json.dumps(record.get("rule_findings", []), ensure_ascii=False),
            record.get("ml_label", "unknown"),
            record.get("ml_spam_probability"),
            record.get("risk_level", "low"),
            int(record.get("risk_score", 0)),
            json.dumps(record.get("indicators", []), ensure_ascii=False),
            record.get("summary", "")[:1000],
            json.dumps(record.get("explanation", {}), ensure_ascii=False),
            int(record.get("processing_ms", 0)),
        )
        with get_connection() as conn:
            cursor = conn.execute(sql, params)
            row_id = int(cursor.lastrowid)
        logger.debug("Saved scan %s (row %s)", record.get("scan_id"), row_id)
        return row_id

    def enforce_max_rows(self, max_rows: int) -> int:
        """
        Delete the oldest rows beyond `max_rows` (privacy + disk hygiene).
        Returns the number of deleted rows.
        """
        if max_rows <= 0:
            return 0
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM scans").fetchone()["c"]
            if total <= max_rows:
                return 0
            to_delete = total - max_rows
            conn.execute(
                """
                DELETE FROM scans
                WHERE id IN (SELECT id FROM scans ORDER BY id ASC LIMIT ?)
                """,
                (to_delete,),
            )
        logger.info("Retention policy removed %s old scan(s)", to_delete)
        return to_delete

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def list_scans(
        self,
        limit: int = 20,
        offset: int = 0,
        risk_level: Optional[str] = None,
        scan_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Paginated history, newest first, with optional filters."""
        clauses: List[str] = []
        params: List[Any] = []

        if risk_level:
            clauses.append("risk_level = ?")
            params.append(risk_level)
        if scan_type:
            clauses.append("scan_type = ?")
            params.append(scan_type)
        if search:
            clauses.append("(message_preview LIKE ? OR summary LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT * FROM scans
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def count_scans(
        self,
        risk_level: Optional[str] = None,
        scan_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        clauses: List[str] = []
        params: List[Any] = []
        if risk_level:
            clauses.append("risk_level = ?")
            params.append(risk_level)
        if scan_type:
            clauses.append("scan_type = ?")
            params.append(scan_type)
        if search:
            clauses.append("(message_preview LIKE ? OR summary LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with get_connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM scans {where}", params).fetchone()
        return int(row["c"])

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    def get_stats(self) -> Dict[str, Any]:
        """Single round trip per metric; returns a plain dict for the router."""
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM scans").fetchone()["c"]

            by_level = {
                row["risk_level"]: row["c"]
                for row in conn.execute(
                    "SELECT risk_level, COUNT(*) AS c FROM scans GROUP BY risk_level"
                ).fetchall()
            }

            by_type = {
                row["scan_type"]: row["c"]
                for row in conn.execute(
                    "SELECT scan_type, COUNT(*) AS c FROM scans GROUP BY scan_type"
                ).fetchall()
            }

            spam = conn.execute(
                "SELECT COUNT(*) AS c FROM scans WHERE ml_label = 'spam'"
            ).fetchone()["c"]

            suspicious_urls = conn.execute(
                """
                SELECT COUNT(*) AS c FROM scans
                WHERE scan_type = 'url' AND risk_score >= 40
                """
            ).fetchone()["c"]

            avg_score = conn.execute(
                "SELECT AVG(risk_score) AS a FROM scans"
            ).fetchone()["a"]

            daily = [
                {"date": row["d"], "count": row["c"]}
                for row in conn.execute(
                    """
                    SELECT substr(created_at, 1, 10) AS d, COUNT(*) AS c
                    FROM scans
                    GROUP BY d
                    ORDER BY d DESC
                    LIMIT 14
                    """
                ).fetchall()
            ]
            daily.reverse()  # chronological for charting

            indicator_rows = conn.execute(
                "SELECT indicators FROM scans ORDER BY id DESC LIMIT 500"
            ).fetchall()

        # Count rule/indicator frequency in Python (JSON column, small volume).
        counter: Dict[str, int] = {}
        for row in indicator_rows:
            for indicator in _safe_json_loads(row["indicators"], []):
                if isinstance(indicator, str):
                    counter[indicator] = counter.get(indicator, 0) + 1
                elif isinstance(indicator, dict):
                    key = str(indicator.get("title") or indicator.get("code") or "")
                    if key:
                        counter[key] = counter.get(key, 0) + 1
        top_indicators = sorted(
            ({"name": k, "count": v} for k, v in counter.items()),
            key=lambda item: item["count"],
            reverse=True,
        )[:8]

        return {
            "total_scans": int(total),
            "spam_detected": int(spam),
            "suspicious_urls": int(suspicious_urls),
            "high_risk_scans": int(by_level.get("high", 0) + by_level.get("critical", 0)),
            "risk_distribution": {
                "low": int(by_level.get("low", 0)),
                "medium": int(by_level.get("medium", 0)),
                "high": int(by_level.get("high", 0)),
                "critical": int(by_level.get("critical", 0)),
            },
            "daily_counts": daily,
            "scans_by_type": {k: int(v) for k, v in by_type.items()},
            "top_indicators": top_indicators,
            "average_risk_score": round(float(avg_score), 1) if avg_score is not None else None,
        }

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def clear_all(self) -> int:
        """Delete every stored scan. Returns rows removed."""
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM scans").fetchone()["c"]
            conn.execute("DELETE FROM scans")
        logger.warning("Cleared %s scan(s) from history", total)
        return int(total)

    def delete_scan(self, scan_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM scans WHERE scan_id = ?", (scan_id,))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        data = dict(row)
        data["rule_findings"] = _safe_json_loads(data.get("rule_findings", "[]"), [])
        data["indicators"] = _safe_json_loads(data.get("indicators", "[]"), [])
        data["explanation"] = _safe_json_loads(data.get("explanation", "{}"), {})
        return data


# Module-level singleton used by the API layer.
scan_repository = ScanRepository()
