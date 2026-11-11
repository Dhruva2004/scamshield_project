"""
ScamShield AI - backend/services/model_registry.py
==================================================
Loads and holds the trained ML artefacts (TF-IDF vectorizer + classifier).

Why a registry instead of loading inside the endpoint?
------------------------------------------------------
Loading a joblib model takes 10-100 ms and a lot of RAM. Doing it per request
would be wasteful, so we load once (lazily, on first use) and keep it in a
module-level singleton.

Crucially, EVERY failure is non-fatal: if the model has not been trained yet,
`is_available` is False and the API keeps working using the rule engine only.
That graceful degradation is an explicit project requirement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib

from backend.config import get_settings
from backend.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class LoadedModel:
    """A vectorizer + classifier pair plus its metadata."""

    classifier: Any
    vectorizer: Any
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.metadata.get("model_name", type(self.classifier).__name__)

    @property
    def version(self) -> str:
        return self.metadata.get("version", "1.0.0")


class ModelRegistry:
    """Lazy, cached access to the active model bundle."""

    def __init__(self) -> None:
        self._bundle: Optional[LoadedModel] = None
        self._load_attempted = False
        self._load_error: Optional[str] = None
        self._metrics: Optional[Dict[str, Any]] = None
        self._comparison: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self, force: bool = False) -> Optional[LoadedModel]:
        """
        Load the active model bundle. Returns None if unavailable.

        The bundle format (see ml/training/train.py) is a dict:
            {"classifier": ..., "vectorizer": ..., "metadata": {...}}
        A bare classifier file is also accepted for robustness.
        """
        if self._bundle is not None and not force:
            return self._bundle
        if self._load_attempted and not force:
            return self._bundle

        self._load_attempted = True
        self._load_error = None
        settings = get_settings()
        model_path = settings.active_model_path

        if not model_path.exists():
            self._load_error = f"Model file not found: {model_path}"
            logger.warning(
                "ML model not available (%s). Run 'python scripts/train_models.py' "
                "to create it. The API will continue with rule-based detection only.",
                self._load_error,
            )
            return None

        try:
            artifact = joblib.load(model_path)
            if isinstance(artifact, dict) and "classifier" in artifact:
                self._bundle = LoadedModel(
                    classifier=artifact["classifier"],
                    vectorizer=artifact.get("vectorizer"),
                    metadata=artifact.get("metadata", {}),
                )
            else:
                # Fallback: a raw estimator saved without a bundle dict.
                self._bundle = LoadedModel(
                    classifier=artifact,
                    vectorizer=None,
                    metadata={"model_name": type(artifact).__name__},
                )
            if self._bundle.vectorizer is None:
                vectorizer_path = settings.vectorizer_dir / "tfidf_vectorizer.joblib"
                if vectorizer_path.exists():
                    self._bundle.vectorizer = joblib.load(vectorizer_path)
            logger.info(
                "Loaded ML model '%s' v%s from %s",
                self._bundle.name,
                self._bundle.version,
                model_path,
            )
            return self._bundle
        except Exception as exc:  # corrupt file, version mismatch, ...
            self._load_error = str(exc)
            logger.error("Failed to load ML model: %s", exc)
            self._bundle = None
            return None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return self.load() is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def metadata(self) -> Dict[str, Any]:
        bundle = self.load()
        return dict(bundle.metadata) if bundle else {}

    def performance_metrics(self) -> Dict[str, Any]:
        """
        Read models/metrics.json (produced by the training script).
        Returns {} when the file does not exist.
        """
        if self._metrics is not None:
            return self._metrics
        metrics_path = Path(get_settings().model_dir) / "metrics.json"
        if not metrics_path.exists():
            self._metrics = {}
            return self._metrics
        try:
            self._metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read %s: %s", metrics_path, exc)
            self._metrics = {}
        return self._metrics

    def comparison_table(self) -> List[Dict[str, Any]]:
        """Rows of the model-comparison table (from models/metrics.json)."""
        payload = self.performance_metrics()
        entries = payload.get("comparison", [])
        return entries if isinstance(entries, list) else []

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------
    def predict_proba(self, cleaned_texts: List[str]) -> Optional[List[float]]:
        """
        Return P(spam) for each already-preprocessed text.

        Returns None when the model is unavailable, so callers can degrade
        gracefully instead of crashing.
        """
        bundle = self.load()
        if bundle is None or bundle.vectorizer is None:
            return None
        try:
            matrix = bundle.vectorizer.transform(cleaned_texts)
            probabilities = bundle.classifier.predict_proba(matrix)
        except Exception as exc:
            logger.error("Inference failed: %s", exc)
            return None

        classes = list(getattr(bundle.classifier, "classes_", []))
        # Locate the positive (spam) column instead of assuming index 1.
        try:
            spam_index = [str(c).lower() for c in classes].index("spam")
        except ValueError:
            spam_index = 1 if len(classes) > 1 else 0
        return [float(row[spam_index]) for row in probabilities]


# Singleton
_registry = ModelRegistry()


def get_model_registry() -> ModelRegistry:
    return _registry


def reset_model_registry() -> None:
    """Used by tests to force a re-read of the artefact from disk."""
    global _registry
    _registry = ModelRegistry()
