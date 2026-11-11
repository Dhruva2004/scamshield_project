"""
ScamShield AI - ml/inference/predictor.py
=========================================
Turns a raw message into an `MLPrediction` for the API.

Responsibilities
----------------
1. Clean the text with the SAME function used during training (`clean_text`).
   Using a different cleaning path here is the single most common cause of
   "the model works in the notebook but not in production".
2. Ask the model registry for P(spam) and convert it to a label + confidence.
3. Explain which tokens pushed the decision (for linear models) so the UI can
   show something more useful than a bare percentage.
4. NEVER claim certainty. Every prediction carries a `note` explaining what
   the number does and does not mean.

Graceful degradation
--------------------
If no artefact exists (you have not trained yet), `predict()` returns
`available=False` and the whole application keeps working on rules alone.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.core.logging_config import get_logger
from backend.schemas.common import ModelInfo
from backend.schemas.scan import MLPrediction
from backend.services.model_registry import get_model_registry
from ml.preprocessing.text_clean import clean_text

logger = get_logger(__name__)

UNAVAILABLE_NOTE = (
    "The machine-learning model is not available, so this scan relies on the rule "
    "engine only. Train it with: python scripts/train_models.py"
)

PROBABILITY_NOTE = (
    "This is the model's estimated spam score, not a guarantee that the message "
    "is fraudulent (or safe). The model was trained on English SMS data; Hindi and "
    "Hinglish messages are not reliably classified."
)


class SpamPredictor:
    """Wraps the registry and produces MLPrediction objects."""

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    # ------------------------------------------------------------------
    def predict(self, text: str) -> MLPrediction:
        """Classify one raw message."""
        registry = get_model_registry()
        bundle = registry.load()

        if bundle is None:
            return MLPrediction(available=False, note=UNAVAILABLE_NOTE)

        cleaned = clean_text(text)
        if not cleaned:
            return MLPrediction(
                available=True,
                label="unknown",
                note="The message contained no analysable words after cleaning.",
                model=ModelInfo(
                    name=bundle.name, version=bundle.version, available=True
                ),
            )

        probabilities = registry.predict_proba([cleaned])
        if probabilities is None:
            return MLPrediction(
                available=False,
                note="The model failed to score this message; rule-based results still apply.",
            )

        spam_probability = float(probabilities[0])
        # A label needs a threshold; 0.5 is the neutral default and is exposed
        # in the API response so the UI can explain the decision boundary.
        threshold = self.threshold
        label = "spam" if spam_probability >= threshold else "ham"
        # Confidence = distance from the boundary, rescaled to 0..1.
        confidence = abs(spam_probability - threshold) / max(threshold, 1 - threshold)

        return MLPrediction(
            available=True,
            label=label,
            spam_probability=round(spam_probability, 4),
            threshold=threshold,
            confidence=round(float(confidence), 4),
            model=ModelInfo(name=bundle.name, version=bundle.version, available=True),
            note=PROBABILITY_NOTE,
        )

    # ------------------------------------------------------------------
    def explain_tokens(self, text: str, top_k: int = 8) -> Dict[str, List[str]]:
        """
        For linear models, list the tokens that pushed towards spam/ham.

        Method: multiply each TF-IDF value by the model's learned coefficient
        for that feature. Summing those contributions gives the decision
        score, so the largest positive contributors are the most "spammy"
        words *in this specific message*.

        Returns {"supports_spam": [...], "supports_ham": [...]}.
        Only meaningful for linear models; other estimators return empty lists.
        """
        registry = get_model_registry()
        bundle = registry.load()
        if bundle is None or bundle.vectorizer is None:
            return {"supports_spam": [], "supports_ham": []}

        classifier = bundle.classifier
        coefficients = getattr(classifier, "coef_", None)
        if coefficients is None:
            # RandomForest / other non-linear models: no per-token linear weights.
            return {"supports_spam": [], "supports_ham": []}

        cleaned = clean_text(text)
        if not cleaned:
            return {"supports_spam": [], "supports_ham": []}

        matrix = bundle.vectorizer.transform([cleaned])
        feature_names = np.asarray(bundle.vectorizer.get_feature_names_out())
        weights = np.asarray(coefficients).ravel()

        row = matrix.tocoo()
        if row.nnz == 0:
            return {"supports_spam": [], "supports_ham": []}

        contributions = [
            (feature_names[idx], float(value * weights[idx]))
            for idx, value in zip(row.col, row.data)
        ]
        contributions.sort(key=lambda item: item[1], reverse=True)

        supports_spam = [token for token, score in contributions if score > 0][:top_k]
        supports_ham = [token for token, score in reversed(contributions) if score < 0][:top_k]
        return {"supports_spam": supports_spam, "supports_ham": supports_ham}

    # ------------------------------------------------------------------
    def predict_batch(self, texts: List[str]) -> List[MLPrediction]:
        """Convenience wrapper; the vectorizer already handles batches."""
        return [self.predict(text) for text in texts]

    # ------------------------------------------------------------------
    def info(self) -> Dict[str, object]:
        """Metadata for /api/v1/models/info."""
        bundle = get_model_registry().load()
        if bundle is None:
            return {"available": False, "reason": get_model_registry().load_error}
        return {"available": True, **bundle.metadata}


_predictor: Optional[SpamPredictor] = None


def get_predictor() -> SpamPredictor:
    """Singleton predictor honouring the configured threshold."""
    global _predictor
    if _predictor is None:
        from backend.config import get_settings

        _predictor = SpamPredictor(threshold=get_settings().ml_spam_threshold)
    return _predictor


def reset_predictor() -> None:
    """Test helper: rebuild the predictor after changing settings."""
    global _predictor
    _predictor = None
