"""
ScamShield AI - ml/evaluation/evaluate.py
=========================================
Re-evaluate a saved model and write human-readable evaluation artefacts.

Why a separate evaluation script?
---------------------------------
Training prints metrics to a terminal and they scroll away. A reviewer (or an
examiner) needs durable evidence. This script loads the persisted bundle,
scores the held-out test split again, and writes:

    ml/evaluation/reports/evaluation_report.md   -> tables for the report
    ml/evaluation/reports/evaluation_report.json -> machine-readable
    ml/evaluation/reports/confusion_matrix.png   -> image for the slides

Run:
    python -m ml.evaluation.evaluate
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.preprocessing.text_clean import clean_batch  # noqa: E402

DATA_CSV = PROJECT_ROOT / "ml" / "data" / "processed" / "sms_spam.csv"
MODEL_DIR = PROJECT_ROOT / "models"
REPORT_DIR = PROJECT_ROOT / "ml" / "evaluation" / "reports"

RANDOM_STATE = 42
TEST_SIZE = 0.20


def _load_split():
    """Rebuild the EXACT same train/test split the training script used."""
    frame = pd.read_csv(DATA_CSV).dropna(subset=["text", "label_encoded"]).copy()
    frame["clean"] = clean_batch(frame["text"].astype(str).tolist())
    frame = frame[frame["clean"].str.len() > 0].reset_index(drop=True)

    _, X_test_text, _, y_test = train_test_split(
        frame["clean"],
        frame["label_encoded"].astype(int),
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=frame["label_encoded"].astype(int),
    )
    return X_test_text, y_test


def _confusion_matrix_ascii(matrix: np.ndarray) -> str:
    """Text-art confusion matrix for terminals and markdown reports."""
    labels = ["ham", "spam"]
    lines = ["", "| actual \\ predicted | pred ham | pred spam |", "|---|---|---|"]
    for index, label in enumerate(labels):
        lines.append(f"| **{label}** | {matrix[index][0]} | {matrix[index][1]} |")
    return "\n".join(lines)


def _write_png(matrix: np.ndarray, path: Path, title: str) -> bool:
    """
    Save a confusion-matrix heatmap with matplotlib if it is installed.

    matplotlib is deliberately NOT a hard requirement: the project must run
    with the minimal dependency set, so we degrade to a text matrix.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")           # headless: never try to open a window
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    fig, ax = plt.subplots(figsize=(4.6, 3.8))
    image = ax.imshow(matrix, cmap="Blues")
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("Actual label")
    ax.set_xticks([0, 1], ["ham", "spam"])
    ax.set_yticks([0, 1], ["ham", "spam"])
    threshold = matrix.max() / 2.0
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(
                j, i, str(matrix[i][j]), ha="center", va="center",
                color="white" if matrix[i][j] > threshold else "black", fontsize=13,
            )
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return True


def evaluate_active_model() -> Dict[str, Any]:
    """Score the persisted active model on the held-out test set."""
    metrics_file = MODEL_DIR / "metrics.json"
    if not metrics_file.exists():
        raise SystemExit("models/metrics.json missing. Run: python scripts/train_models.py")
    payload = json.loads(metrics_file.read_text(encoding="utf-8"))

    model_name = payload.get("model_name", "")
    key = payload.get("model_key") or model_name.lower().replace(" ", "_")
    model_path = MODEL_DIR / f"model_{key}.joblib"
    if not model_path.exists():
        candidate = MODEL_DIR / payload.get("active_model_file", "")
        model_path = candidate if candidate.exists() else model_path
    if not model_path.exists():
        raise SystemExit(f"Model artefact not found in {MODEL_DIR}. Re-run training.")

    bundle = joblib.load(model_path)
    classifier = bundle["classifier"]
    vectorizer = bundle["vectorizer"]

    X_test_text, y_test = _load_split()
    X_test = vectorizer.transform(X_test_text)

    predictions = classifier.predict(X_test)
    probabilities = (
        classifier.predict_proba(X_test)[:, 1]
        if hasattr(classifier, "predict_proba")
        else None
    )

    matrix = confusion_matrix(y_test, predictions)
    metrics = {
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)) if probabilities is not None else None,
        "confusion_matrix": matrix.tolist(),
        "test_size": int(len(y_test)),
        "true_positives": int(matrix[1][1]),
        "false_negatives": int(matrix[1][0]),
        "false_positives": int(matrix[0][1]),
        "true_negatives": int(matrix[0][0]),
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "evaluation_report.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": model_name,
                "artefact": model_path.name,
                "dataset": payload.get("dataset"),
                "metrics": metrics,
                "comparison": payload.get("comparison", []),
                "selection_reason": payload.get("selection_reason", ""),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- Markdown report -------------------------------------------------
    rows = [
        "| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | Chosen |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in payload.get("comparison", []):
        rows.append(
            f"| {entry['model_name']} | {entry['accuracy']:.4f} | {entry['precision']:.4f} | "
            f"{entry['recall']:.4f} | {entry['f1']:.4f} | "
            f"{(entry.get('roc_auc') or 0):.4f} | {'✅' if entry.get('chosen') else ''} |"
        )

    markdown = f"""# ScamShield AI — Model Evaluation Report

Generated: {datetime.now(timezone.utc).isoformat(timespec="seconds")}

## Dataset
* **Source:** {payload.get('dataset')}
* **Train / test split:** {payload.get('train_size'):,} / {payload.get('test_size'):,} (stratified, 80/20)
* **Random state:** {payload.get('random_state')} (reproducible)
* **Cross-validation:** {payload.get('cv_folds')}-fold stratified on the training set

## Algorithm comparison (held-out test set)

{chr(10).join(rows)}

## Selected model: {model_name}

{payload.get('selection_reason', '')}

## Confusion matrix
{_confusion_matrix_ascii(matrix)}

* True positives (spam caught): **{metrics['true_positives']}**
* False negatives (spam missed): **{metrics['false_negatives']}**
* False positives (safe message flagged): **{metrics['false_positives']}**
* True negatives (safe message correctly passed): **{metrics['true_negatives']}**

## Why F1 and recall, not accuracy
The dataset is only ~12% spam. A model that always answers "ham" would score
~88% accuracy while catching zero scams. Recall measures how many real scams we
catch; precision measures how often our alarm is right; F1 balances the two.

## Limitations
* English SMS only — Hindi/Hinglish messages are handled by curated rules, not this model.
* Training vocabulary is 2005-era UK/US SMS; modern UPI/KYC phishing wording is
  covered by the rule engine.
* The output is a model score, never a guarantee of fraud or safety.
"""
    md_path = REPORT_DIR / "evaluation_report.md"
    md_path.write_text(markdown, encoding="utf-8")

    png_path = REPORT_DIR / "confusion_matrix.png"
    png_written = _write_png(matrix, png_path, f"Confusion matrix — {model_name}")

    print(f"[evaluate] model      : {model_name} ({model_path.name})")
    print(f"[evaluate] accuracy   : {metrics['accuracy']:.4f}")
    print(f"[evaluate] precision  : {metrics['precision']:.4f}")
    print(f"[evaluate] recall     : {metrics['recall']:.4f}")
    print(f"[evaluate] f1         : {metrics['f1']:.4f}")
    if metrics["roc_auc"]:
        print(f"[evaluate] roc_auc    : {metrics['roc_auc']:.4f}")
    print(_confusion_matrix_ascii(matrix))
    print(f"[evaluate] wrote {json_path.name}, {md_path.name}"
          + (f", {png_path.name}" if png_written else " (matplotlib not installed: no PNG)"))

    return metrics


if __name__ == "__main__":
    evaluate_active_model()
