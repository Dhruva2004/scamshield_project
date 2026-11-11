"""
ScamShield AI - backend/api/history.py
======================================
Scan history + dashboard statistics endpoints.

Routes
------
GET    /api/v1/history              paginated, filterable history
GET    /api/v1/history/{scan_id}    a single stored scan
DELETE /api/v1/history              clear everything (privacy control)
DELETE /api/v1/history/{scan_id}    delete one scan
GET    /api/v1/history/stats        dashboard aggregates
GET    /api/v1/history/export.csv   CSV export of stored scans
"""

from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.api.dependencies import require_api_key
from backend.config import get_settings
from backend.core.logging_config import get_logger
from backend.database.repositories import scan_repository
from backend.schemas.common import RiskLevel, ScanType
from backend.schemas.evaluation import ModelPerformance
from backend.schemas.history import (
    ClearHistoryResponse,
    HistoryDetail,
    HistoryItem,
    HistoryPage,
    StatsResponse,
)
from backend.services.model_registry import get_model_registry

logger = get_logger(__name__)

router = APIRouter(prefix="/history", tags=["history"], dependencies=[Depends(require_api_key)])


def _to_history_item(row: dict) -> HistoryItem:
    """Map a database row (snake_case dict) to the public schema."""
    indicators = [
        item.get("title") if isinstance(item, dict) else str(item)
        for item in row.get("indicators", [])
    ]
    return HistoryItem(
        id=int(row["id"]),
        scan_id=row["scan_id"],
        created_at=row["created_at"],
        scan_type=row.get("scan_type", "message"),
        language=row.get("language", "en"),
        risk_level=row.get("risk_level", "low"),
        risk_score=int(row.get("risk_score", 0)),
        rule_score=int(row.get("rule_score", 0)),
        ml_label=row.get("ml_label", "unknown"),
        ml_spam_probability=row.get("ml_spam_probability"),
        message_preview=row.get("message_preview", ""),
        indicators=[i for i in indicators if i],
        summary=row.get("summary", ""),
    )


@router.get("", response_model=HistoryPage, summary="List stored scans (newest first)")
def list_history(
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(20, ge=1, le=100, description="Rows per page"),
    risk_level: Optional[RiskLevel] = Query(None, description="Filter by risk level"),
    scan_type: Optional[ScanType] = Query(None, description="Filter by artifact type"),
    search: Optional[str] = Query(None, max_length=100, description="Substring search"),
) -> HistoryPage:
    offset = (page - 1) * page_size
    rows = scan_repository.list_scans(
        limit=page_size,
        offset=offset,
        risk_level=risk_level.value if risk_level else None,
        scan_type=scan_type.value if scan_type else None,
        search=search,
    )
    total = scan_repository.count_scans(
        risk_level=risk_level.value if risk_level else None,
        scan_type=scan_type.value if scan_type else None,
        search=search,
    )
    return HistoryPage(
        items=[_to_history_item(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + len(rows) < total,
    )


@router.get("/stats", response_model=StatsResponse, summary="Dashboard statistics")
def get_stats() -> StatsResponse:
    """
    Aggregated numbers for the dashboard: totals, risk distribution, daily
    trend, top indicators and the ML model's evaluation metrics.
    """
    raw = scan_repository.get_stats()

    # Attach real model metrics from the artefact saved during training.
    registry = get_model_registry()
    performance = ModelPerformance(available=False)
    metrics = registry.performance_metrics()
    if metrics:
        performance = ModelPerformance(
            available=True,
            model_name=metrics.get("model_name", "unknown"),
            dataset=metrics.get("dataset", ""),
            accuracy=metrics.get("accuracy"),
            precision=metrics.get("precision"),
            recall=metrics.get("recall"),
            f1=metrics.get("f1"),
            confusion_matrix=metrics.get("confusion_matrix"),
            trained_at=metrics.get("trained_at"),
        )

    return StatsResponse(
        total_scans=raw["total_scans"],
        spam_detected=raw["spam_detected"],
        suspicious_urls=raw["suspicious_urls"],
        high_risk_scans=raw["high_risk_scans"],
        risk_distribution=raw["risk_distribution"],
        daily_counts=raw["daily_counts"],
        scans_by_type=raw["scans_by_type"],
        top_indicators=raw["top_indicators"],
        average_risk_score=raw["average_risk_score"],
        model_performance=performance,
    )


@router.get("/export.csv", summary="Export history as CSV")
def export_csv() -> StreamingResponse:
    """
    Stream the newest 1,000 scans as CSV. Streaming avoids building the whole
    file in memory, which matters for large histories.
    """
    rows = scan_repository.list_scans(limit=1000, offset=0)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "scan_id", "created_at", "scan_type", "language", "risk_level",
            "risk_score", "rule_score", "ml_label", "ml_spam_probability",
            "indicators", "summary", "message_preview",
        ]
    )
    for row in rows:
        indicators = "; ".join(
            item.get("title", "") if isinstance(item, dict) else str(item)
            for item in row.get("indicators", [])
        )
        writer.writerow(
            [
                row["scan_id"], row["created_at"], row["scan_type"], row["language"],
                row["risk_level"], row["risk_score"], row["rule_score"],
                row["ml_label"], row["ml_spam_probability"], indicators,
                row["summary"], row["message_preview"],
            ]
        )
    buffer.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="scamshield_history.csv"'}
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers=headers)


@router.delete("", response_model=ClearHistoryResponse, summary="Clear all history")
def clear_history() -> ClearHistoryResponse:
    """Delete every stored scan. Irreversible - the UI asks for confirmation."""
    deleted = scan_repository.clear_all()
    return ClearHistoryResponse(deleted=deleted, message=f"Deleted {deleted} scan record(s).")


@router.get(
    "/{scan_id}",
    response_model=HistoryDetail,
    summary="Fetch one stored scan (raw text requires explicit opt-in)",
)
def get_history_item(
    scan_id: str,
    include_raw: bool = Query(
        False,
        description="Return the original message text. Requires STORE_RAW_MESSAGE=true.",
    ),
) -> HistoryDetail:
    row = scan_repository.get_scan(scan_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan '{scan_id}' not found"
        )

    settings = get_settings()
    raw_allowed = include_raw and settings.store_raw_message
    # Even with opt-in, we never return text if the deployment forbids storing it.
    row["raw_message"] = row.get("raw_message") if raw_allowed else None

    return HistoryDetail(**{key: row.get(key) for key in HistoryDetail.model_fields})


@router.delete("/{scan_id}", response_model=ClearHistoryResponse, summary="Delete one scan")
def delete_history_item(scan_id: str) -> ClearHistoryResponse:
    if not scan_repository.delete_scan(scan_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan '{scan_id}' not found"
        )
    settings = get_settings()
    logger.info("Deleted scan %s (retention limit %s)", scan_id, settings.history_max_rows)
    return ClearHistoryResponse(deleted=1, message="Scan deleted.")
