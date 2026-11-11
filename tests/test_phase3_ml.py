"""
ScamShield AI - tests/test_phase3_ml.py
=======================================
Tests for the ML layer: text cleaning, model quality, persistence, inference.

These tests require a trained artefact. If `models/metrics.json` is missing they
are SKIPPED (not failed) with a message telling you how to create it - a fresh
clone must never show red tests just because training has not run yet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
METRICS_PATH = PROJECT_ROOT / "models" / "metrics.json"
MODEL_PATH = PROJECT_ROOT / "models" / "model_logistic_regression.joblib"

requires_model = pytest.mark.skipif(
    not METRICS_PATH.exists(),
    reason="No trained model. Run: python scripts/train_models.py",
)


def _metrics() -> dict:
    return json.loads(METRICS_PATH.read_text(encoding="utf-8"))


class TestTextCleaning:
    def test_url_replaced_by_placeholder(self):
        from ml.preprocessing.text_clean import clean_text

        assert "<url>" in clean_text("visit https://evil.xyz/login now")
        assert "evil.xyz" not in clean_text("visit https://evil.xyz/login now")

    def test_money_replaced(self):
        from ml.preprocessing.text_clean import clean_text

        assert "<money>" in clean_text("you won Rs 5000 today")

    def test_phone_replaced(self):
        from ml.preprocessing.text_clean import clean_text

        cleaned = clean_text("call 09061701461 now")
        assert "09061701461" not in cleaned

    def test_lowercased_and_punctuation_free(self):
        from ml.preprocessing.text_clean import clean_text

        assert clean_text("HELLO!!! World.") == "hello world"

    def test_repeated_letters_collapsed(self):
        from ml.preprocessing.text_clean import clean_text

        assert "fre" in clean_text("freeeee")

    def test_empty_input_safe(self):
        from ml.preprocessing.text_clean import clean_text

        assert clean_text("") == ""
        assert clean_text(None) == ""

    def test_batch_matches_single(self):
        from ml.preprocessing.text_clean import clean_batch, clean_text

        texts = ["one http://a.xyz", "two Rs 10"]
        assert clean_batch(texts) == [clean_text(t) for t in texts]


class TestDataset:
    @pytest.mark.skipif(
        not (PROJECT_ROOT / "ml" / "data" / "processed" / "sms_spam.csv").exists(),
        reason="Dataset not prepared. Run: python -m ml.data.download_dataset",
    )
    def test_dataset_has_expected_shape(self):
        import pandas as pd

        frame = pd.read_csv(PROJECT_ROOT / "ml" / "data" / "processed" / "sms_spam.csv")
        assert {"label", "text", "label_encoded"}.issubset(frame.columns)
        # UCI SMS Spam Collection has 5,572 raw rows; ~414 duplicates removed.
        assert 5000 < len(frame) < 5600
        assert set(frame["label_encoded"].unique()) == {0, 1}
        # Spam must remain the minority class - this is why accuracy is misleading.
        assert 0.05 < frame["label_encoded"].mean() < 0.20


@requires_model
class TestModelQuality:
    """Assert the MEASURED metrics meet a minimum bar (no invented numbers)."""

    def test_metrics_file_is_real(self):
        payload = _metrics()
        for key in ("accuracy", "precision", "recall", "f1", "confusion_matrix", "comparison"):
            assert key in payload, f"metrics.json is missing '{key}'"
        assert payload["dataset"].startswith("UCI SMS Spam Collection")
        assert len(payload["comparison"]) >= 2, "at least two algorithms must be compared"

    def test_accuracy_above_threshold(self):
        """98% is a conservative bar for this dataset (we measured 98.5%)."""
        assert _metrics()["accuracy"] > 0.97

    def test_spam_recall_above_threshold(self):
        """Recall matters most: a missed scam costs the user money."""
        assert _metrics()["recall"] > 0.85

    def test_spam_precision_above_threshold(self):
        assert _metrics()["precision"] > 0.85

    def test_f1_above_threshold(self):
        assert _metrics()["f1"] > 0.85

    def test_comparison_contains_three_algorithms(self):
        names = {row["model_name"] for row in _metrics()["comparison"]}
        assert {"MultinomialNB", "LogisticRegression", "RandomForest"} <= names

    def test_exactly_one_model_is_chosen(self):
        chosen = [row for row in _metrics()["comparison"] if row.get("chosen")]
        assert len(chosen) == 1

    def test_confusion_matrix_is_consistent(self):
        metrics = _metrics()
        matrix = metrics["confusion_matrix"]
        assert len(matrix) == 2 and len(matrix[0]) == 2
        assert sum(sum(row) for row in matrix) == metrics["test_size"]
        # TN + FP + FN + TP must reproduce accuracy.
        correct = matrix[0][0] + matrix[1][1]
        assert abs(correct / metrics["test_size"] - metrics["accuracy"]) < 1e-3

    def test_selection_reason_is_documented(self):
        assert len(_metrics()["selection_reason"]) > 40


@requires_model
class TestModelPersistenceAndInference:
    def test_bundle_contains_classifier_and_vectorizer(self):
        import joblib

        path = PROJECT_ROOT / "models" / _metrics()["active_model_file"]
        bundle = joblib.load(path)
        assert {"classifier", "vectorizer", "metadata"} <= set(bundle.keys())

    def test_metadata_records_limitations(self):
        import joblib

        path = PROJECT_ROOT / "models" / _metrics()["active_model_file"]
        metadata = joblib.load(path)["metadata"]
        assert metadata["language"] == "en"
        assert any("Hindi" in item for item in metadata["limitations"])

    def test_predictor_returns_probability(self):
        from ml.inference.predictor import SpamPredictor

        prediction = SpamPredictor().predict("WINNER! You have won a free cash prize, call now!")
        assert prediction.available is True
        assert prediction.spam_probability is not None
        assert 0.0 <= prediction.spam_probability <= 1.0

    def test_obvious_spam_scores_higher_than_obvious_ham(self):
        from ml.inference.predictor import SpamPredictor

        predictor = SpamPredictor()
        spam = predictor.predict("CONGRATULATIONS! You won £2000 cash. Call now to claim!")
        ham = predictor.predict("Hey, I'll be home by 7, can you get milk?")
        assert spam.spam_probability > ham.spam_probability

    def test_prediction_carries_disclaimer(self):
        from ml.inference.predictor import SpamPredictor

        prediction = SpamPredictor().predict("some message")
        assert "not a guarantee" in prediction.note.lower()

    def test_token_explanation_available_for_linear_model(self):
        """LogisticRegression must expose per-token contributions."""
        from ml.inference.predictor import SpamPredictor

        explanation = SpamPredictor().explain_tokens("win free cash prize call now")
        assert explanation["supports_spam"], "linear model should expose spam-supporting tokens"

    def test_empty_text_does_not_crash(self):
        from ml.inference.predictor import SpamPredictor

        prediction = SpamPredictor().predict("   ")
        assert prediction.available is True
        assert prediction.label == "unknown"
