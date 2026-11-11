"""
ScamShield AI - backend/api/models.py
=====================================
Endpoints describing the ML artefacts.

GET /api/v1/models/comparison  - algorithm comparison table (real metrics)
GET /api/v1/models/info        - metadata of the active artefact
GET /api/v1/models/terms       - top spam/ham terms from the linear model

These exist so the dashboard shows genuine measured numbers instead of
hard-coded ones - a common failure mode in student projects.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
from fastapi import APIRouter

from backend.config import get_settings
from backend.schemas.evaluation import ModelComparisonEntry, ModelComparisonResponse
from backend.services.model_registry import get_model_registry

router = APIRouter(prefix="/models", tags=["models"])


@router.get(
    "/comparison",
    response_model=ModelComparisonResponse,
    summary="Algorithm comparison with real evaluation metrics",
)
def model_comparison() -> ModelComparisonResponse:
    """
    Read `models/metrics.json` (written by scripts/train_models.py).

    If the file is missing the endpoint returns `available=false` with an
    explanatory message instead of an error, so the UI can tell the user to
    run training.
    """
    registry = get_model_registry()
    payload = registry.performance_metrics()
    if not payload:
        return ModelComparisonResponse(
            available=False,
            selection_reason=(
                "No metrics found. Run: python scripts/train_models.py"
            ),
        )

    entries: List[ModelComparisonEntry] = []
    for row in payload.get("comparison", []):
        entries.append(
            ModelComparisonEntry(
                model_name=row.get("model_name", "unknown"),
                accuracy=row.get("accuracy", 0.0),
                precision=row.get("precision", 0.0),
                recall=row.get("recall", 0.0),
                f1=row.get("f1", 0.0),
                roc_auc=row.get("roc_auc"),
                train_seconds=row.get("train_seconds"),
                chosen=bool(row.get("chosen")),
            )
        )

    return ModelComparisonResponse(
        available=True,
        dataset=payload.get("dataset", ""),
        vectorizer="TF-IDF (1-2 grams, min_df=2, max_df=0.9, sublinear_tf)",
        trained_at=payload.get("trained_at"),
        active_model=payload.get("model_name", ""),
        entries=entries,
        selection_reason=payload.get("selection_reason", ""),
        cross_validation={
            "folds": payload.get("cv_folds", 0),
            "note": "Stratified K-Fold on the training split",
        },
    )


@router.get("/info", summary="Metadata of the active model artefact")
def model_info() -> Dict[str, Any]:
    """Version, dataset, sizes, limitations and measured test metrics."""
    registry = get_model_registry()
    metadata = registry.metadata()
    settings = get_settings()

    if not metadata:
        return {
            "available": False,
            "reason": registry.load_error or "No model artefact found.",
            "expected_path": str(settings.active_model_path),
            "remedy": "Run: python scripts/train_models.py",
        }
    return {"available": True, **metadata}


@router.get("/terms", summary="Top spam and ham terms learned by the model")
def model_terms(top_k: int = 25) -> Dict[str, Any]:
    """
    Inspect the linear model's coefficients.

    This is the interpretability payoff of choosing Logistic Regression: the
    most positive coefficients are the words that most push a message towards
    "spam". For non-linear models we return an explanatory message instead of
    pretending the concept applies.
    """
    registry = get_model_registry()
    bundle = registry.load()
    if bundle is None:
        return {"available": False, "reason": "No model loaded."}

    coefficients = getattr(bundle.classifier, "coef_", None)
    if coefficients is None or bundle.vectorizer is None:
        return {
            "available": False,
            "reason": (
                f"{bundle.name} is not a linear model, so it has no per-term "
                "coefficients. Train the Logistic Regression model to use this view."
            ),
        }

    feature_names = np.asarray(bundle.vectorizer.get_feature_names_out())
    weights = np.asarray(coefficients).ravel()
    order = np.argsort(weights)

    top_spam = [
        {"term": str(feature_names[i]), "weight": round(float(weights[i]), 4)}
        for i in order[::-1][:top_k]
    ]
    top_ham = [
        {"term": str(feature_names[i]), "weight": round(float(weights[i]), 4)}
        for i in order[:top_k]
    ]
    return {
        "available": True,
        "model": bundle.name,
        "note": (
            "Weights are log-odds contributions from TF-IDF features. They show what the "
            "model learned from the training data - they are not a list of 'bad words'."
        ),
        "top_spam_terms": top_spam,
        "top_ham_terms": top_ham,
    }
