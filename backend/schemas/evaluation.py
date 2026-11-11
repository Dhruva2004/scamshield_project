"""
ScamShield AI - backend/schemas/evaluation.py
=============================================
Schemas describing how well the trained ML model performs.

These values are NOT invented: they are read from
`models/metrics.json`, which is written by scripts/train_models.py after a real
run on the real dataset.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ModelPerformance(BaseModel):
    """Evaluation summary for the currently active model."""

    available: bool = False
    model_name: str = "unavailable"
    dataset: str = ""
    trained_at: Optional[str] = None
    train_size: Optional[int] = None
    test_size: Optional[int] = None
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    roc_auc: Optional[float] = None
    confusion_matrix: Optional[List[List[int]]] = None
    notes: str = ""


class ModelComparisonEntry(BaseModel):
    """One row of the algorithm comparison table."""

    model_name: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: Optional[float] = None
    train_seconds: Optional[float] = None
    chosen: bool = False


class ModelComparisonResponse(BaseModel):
    """Comparison of all trained algorithms, read from models/metrics.json."""

    available: bool = False
    dataset: str = ""
    vectorizer: str = ""
    trained_at: Optional[str] = None
    active_model: str = ""
    entries: List[ModelComparisonEntry] = Field(default_factory=list)
    selection_reason: str = ""
    # Mixed types on purpose: {"folds": 5, "note": "..."}
    cross_validation: Optional[Dict[str, Any]] = None
