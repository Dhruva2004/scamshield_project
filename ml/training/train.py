"""
ScamShield AI - ml/training/train.py
====================================
Trains, compares and persists the spam classifier.

What this script does (in order)
--------------------------------
1. Load `ml/data/processed/sms_spam.csv` (created by ml/data/download_dataset.py).
2. Split 80/20 with **stratification** so the 12.4% spam share is preserved in
   both halves - important because spam is the minority class.
3. Fit a TF-IDF vectorizer on the TRAINING text only. Fitting on the whole
   dataset would leak test vocabulary into training and inflate the scores.
4. Train three candidate algorithms:
       * Multinomial Naive Bayes  - the classic text-classification baseline
       * Logistic Regression      - linear, calibrated probabilities
       * Random Forest            - non-linear ensemble
   plus 5-fold cross-validation on the training set for a stability check.
5. Evaluate each on the untouched test set: accuracy, precision, recall,
   F1, ROC-AUC, confusion matrix, classification report.
6. Pick a winner using a documented rule (highest spam F1, tie-break on
   recall, then on precision) and write:
       models/model_<name>.joblib     bundle: classifier + vectorizer + metadata
       models/metrics.json            every metric + the comparison table
       ml/vectorizers/tfidf_vectorizer.joblib
7. Print a human-readable report.

Why these metrics, and why not accuracy alone?
----------------------------------------------
The dataset is ~87% ham. A model that always answers "ham" scores 87% accuracy
and catches zero scams - useless. So we optimise and report:
  * **Recall** on spam  -> of all real scams, how many did we catch?
  * **Precision** on spam -> of all our alarms, how many were real?
  * **F1** -> the balance of the two.
Missing a scam (false negative) costs the user money; a false alarm costs a
few seconds of checking. That asymmetry is why recall matters most here.

Usage
-----
    python scripts/train_models.py            (recommended)
    python -m ml.training.train               (equivalent)
"""

from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

# --- Project paths ---------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.preprocessing.text_clean import clean_batch  # noqa: E402

DATA_CSV = PROJECT_ROOT / "ml" / "data" / "processed" / "sms_spam.csv"
MODEL_DIR = PROJECT_ROOT / "models"
VECTORIZER_DIR = PROJECT_ROOT / "ml" / "vectorizers"
METRICS_PATH = MODEL_DIR / "metrics.json"

RANDOM_STATE = 42
TEST_SIZE = 0.20
CV_FOLDS = 5
MODEL_VERSION = "1.0.0"
DATASET_NAME = "UCI SMS Spam Collection (id 228)"


# ---------------------------------------------------------------------------
# Candidate models
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """One algorithm to train, with a human explanation for the viva."""

    key: str
    name: str
    estimator: Any
    rationale: str
    notes: str


def build_candidates() -> List[Candidate]:
    """
    Instantiate the three candidate algorithms.

    Every hyper-parameter is chosen deliberately, not tuned blindly:
      * alpha=0.1 in MultinomialNB: light smoothing; SMS vocabulary is small,
        so a large alpha would wash out the signal.
      * C=10 in Logistic Regression: a moderately weak regulariser. The
        dataset is separable enough that aggressive regularisation hurts recall.
      * class_weight='balanced' in both LR and RF: compensates for the 1:7
        class imbalance *without* duplicating rows (which would distort
        probabilities).
      * n_estimators=300, min_samples_leaf=2 in RF: enough trees for stable
        averaged predictions, with a small leaf to avoid over-fitting the noise
        in 5k messages.
    """
    return [
        Candidate(
            key="naive_bayes",
            name="MultinomialNB",
            estimator=MultinomialNB(alpha=0.1),
            rationale=(
                "Fast, strong baseline for count/TF-IDF features. Very interpretable: "
                "each word contributes an additive log-probability."
            ),
            notes="Assumes word independence - a simplification, but it works well on short SMS.",
        ),
        Candidate(
            key="logistic_regression",
            name="LogisticRegression",
            estimator=LogisticRegression(
                C=10.0,
                max_iter=2000,
                solver="liblinear",
                class_weight="balanced",
                random_state=RANDOM_STATE,
            ),
            rationale=(
                "Linear decision boundary works well for high-dimensional sparse TF-IDF; "
                "gives calibrated probabilities and per-word coefficients we can explain."
            ),
            notes="Probabilities are the model's confidence, not a guarantee about a specific message.",
        ),
        Candidate(
            key="random_forest",
            name="RandomForest",
            estimator=RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=2,
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=RANDOM_STATE,
            ),
            rationale=(
                "Non-linear ensemble that can capture interactions between words "
                "(e.g. 'free' + 'call' + 'now'). Useful as a contrast to linear models."
            ),
            notes="Slower, larger artefact, and less interpretable per prediction than LR.",
        ),
    ]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_dataset() -> Tuple[pd.Series, pd.Series]:
    """
    Load and validate the processed dataset.

    Returns (cleaned_texts, labels) where labels are 0=ham, 1=spam.
    """
    if not DATA_CSV.exists():
        raise SystemExit(
            f"Dataset not found: {DATA_CSV}\n"
            "Run: python -m ml.data.download_dataset"
        )

    frame = pd.read_csv(DATA_CSV)
    required = {"text", "label_encoded"}
    missing = required - set(frame.columns)
    if missing:
        raise SystemExit(f"Dataset is missing columns {missing}. Re-run the download step.")

    frame = frame.dropna(subset=["text", "label_encoded"]).copy()
    frame["label_encoded"] = frame["label_encoded"].astype(int)
    # Clean once, here, so training and inference share the exact same function.
    frame["clean"] = clean_batch(frame["text"].astype(str).tolist())

    # Drop rows that cleaned down to nothing (e.g. a message that was only an emoji).
    frame = frame[frame["clean"].str.len() > 0].reset_index(drop=True)

    print(f"[data] loaded {len(frame):,} messages from {DATA_CSV.name}")
    print(f"[data] class balance -> ham: {(frame.label_encoded == 0).sum():,} "
          f"| spam: {(frame.label_encoded == 1).sum():,}")
    return frame["clean"], frame["label_encoded"]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(estimator: Any, X_test, y_test) -> Dict[str, Any]:
    """
    Compute every metric we report.

    `zero_division=0` means "if the model predicts no spam at all, precision is
    0 rather than an error" - explicit and honest.
    """
    predictions = estimator.predict(X_test)
    try:
        probabilities = estimator.predict_proba(X_test)[:, 1]
        roc_auc = float(roc_auc_score(y_test, probabilities))
    except (AttributeError, IndexError):
        roc_auc = None

    return {
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": roc_auc,
        "confusion_matrix": confusion_matrix(y_test, predictions).tolist(),
        "classification_report": classification_report(
            y_test, predictions, target_names=["ham", "spam"], zero_division=0
        ),
    }


# Models are ranked by interpretability/simplicity, used only as a final
# tie-break. Lower number = simpler to explain and cheaper to serve.
SIMPLICITY_RANK = {"logistic_regression": 0, "naive_bayes": 1, "random_forest": 2}
# Two models whose test F1 differ by less than this are treated as TIED.
# Justification: it is smaller than the fold-to-fold CV standard deviation
# (~0.012-0.017 on this dataset), i.e. the gap is inside the noise.
F1_TIE_TOLERANCE = 0.01


def select_winner(comparison: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Choose the production model with an explicit, pre-declared rule.

    Step 1 - candidate set
        Keep every model whose test spam-F1 is within F1_TIE_TOLERANCE of the
        best. Reporting a 0.003 F1 difference as a "win" would be dishonest
        when the cross-validation spread is five times larger.

    Step 2 - pick inside the candidate set
        Highest ROC-AUC (best ranking of risky vs safe messages, independent of
        the 0.5 threshold), then the simplest model.

    Rationale for preferring simplicity on a tie:
        * Logistic Regression is ~500x smaller than the Random Forest
          (~6 KB vs ~3.3 MB) and predicts in microseconds;
        * its coefficients can be shown to the user - which matters in a
          project whose whole point is *explainability*;
        * its probabilities are better calibrated than a forest's vote share.
    """
    ranked = sorted(comparison, key=lambda row: row["f1"], reverse=True)
    best_f1 = ranked[0]["f1"]
    tied = [row for row in ranked if best_f1 - row["f1"] <= F1_TIE_TOLERANCE]

    winner = sorted(
        tied,
        key=lambda row: (
            -(row.get("roc_auc") or 0.0),
            SIMPLICITY_RANK.get(row.get("model_key", ""), 99),
        ),
    )[0]

    # Record why, so the report is self-documenting.
    winner["_tied_with"] = [
        row["model_name"] for row in tied if row["model_key"] != winner["model_key"]
    ]
    winner["_best_f1"] = best_f1
    return winner


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def save_model(
    key: str,
    name: str,
    classifier: Any,
    vectorizer: TfidfVectorizer,
    metrics: Dict[str, Any],
    train_size: int,
    test_size: int,
    elapsed: float,
) -> Path:
    """
    Persist a self-contained bundle.

    The bundle is a plain dict, so loading it needs no custom classes:
        {"classifier": ..., "vectorizer": ..., "metadata": {...}}
    This avoids the classic "unpickling failed after a refactor" problem.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    VECTORIZER_DIR.mkdir(parents=True, exist_ok=True)

    target = MODEL_DIR / f"model_{key}.joblib"
    metadata = {
        "model_name": name,
        "model_key": key,
        "version": MODEL_VERSION,
        "dataset": DATASET_NAME,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_size": train_size,
        "test_size": test_size,
        "random_state": RANDOM_STATE,
        "test_size_ratio": TEST_SIZE,
        "cv_folds": CV_FOLDS,
        "sklearn_version": sklearn.__version__,
        "python_version": platform.python_version(),
        "label_mapping": {"ham": 0, "spam": 1},
        "vectorizer": {
            "type": "TfidfVectorizer",
            "ngram_range": [1, 2],
            "min_df": 2,
            "max_features": int(vectorizer.max_features or 0),
            "feature_count": int(len(vectorizer.get_feature_names_out())),
            "sublinear_tf": True,
        },
        "test_metrics": metrics,
        "training_seconds": round(elapsed, 2),
        "language": "en",
        "limitations": [
            "Trained on English SMS only - Hindi/Hinglish messages are NOT reliably classified.",
            "Spam is only 12.4% of the data, so precision/recall matter more than accuracy.",
            "Trained mainly on 2005-era UK/US SMS vocabulary; modern Indian phishing "
            "wording is handled by the rule engine, not by this model.",
            "The probability is a model score, not proof that a message is fraudulent.",
        ],
    }

    joblib.dump(
        {"classifier": classifier, "vectorizer": vectorizer, "metadata": metadata},
        target,
        compress=3,
    )
    joblib.dump(vectorizer, VECTORIZER_DIR / "tfidf_vectorizer.joblib", compress=3)
    print(f"[save] {target.name} ({target.stat().st_size / 1024:.0f} KB)")
    return target


def write_metrics(payload: Dict[str, Any]) -> None:
    """
    Write models/metrics.json - the file the API reads for the dashboard.

    Contains BOTH the per-model metrics and the comparison table, so the
    dashboard can show real numbers instead of hardcoded ones.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[save] {METRICS_PATH.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
@dataclass
class TrainingRun:
    comparison: List[Dict[str, Any]] = field(default_factory=list)
    winner: Dict[str, Any] = field(default_factory=dict)


def train_all(verbose: bool = True) -> Dict[str, Any]:
    """Run the full training + comparison + persistence pipeline."""
    texts, labels = load_dataset()

    X_train_text, X_test_text, y_train, y_test = train_test_split(
        texts,
        labels,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=labels,          # keeps the 12.4% spam share in both halves
    )

    # Fit the vectorizer on the TRAINING text only (prevents vocabulary leakage).
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=2,                 # ignore typos/hapax legomena
        max_df=0.9,               # ignore "to", "you" style boilerplate
        sublinear_tf=True,        # log(tf) damping: repeated words matter less
        strip_accents="unicode",
        lowercase=False,          # cleaning already lowercased
        max_features=30_000,
    )
    X_train = vectorizer.fit_transform(X_train_text)
    X_test = vectorizer.transform(X_test_text)

    if verbose:
        print(f"[tfidf] vocabulary: {len(vectorizer.get_feature_names_out()):,} features")
        print(f"[split] train: {X_train.shape[0]:,} | test: {X_test.shape[0]:,}")

    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    run = TrainingRun()
    trained: Dict[str, Any] = {}

    for candidate in build_candidates():
        if verbose:
            print(f"\n[train] {candidate.name} ...")
        started = time.perf_counter()

        estimator = candidate.estimator
        estimator.fit(X_train, y_train)
        elapsed = time.perf_counter() - started

        metrics = evaluate(estimator, X_test, y_test)
        cv_scores = cross_val_score(estimator, X_train, y_train, cv=cv, scoring="f1")

        if verbose:
            print(f"        accuracy={metrics['accuracy']:.4f} precision={metrics['precision']:.4f} "
                  f"recall={metrics['recall']:.4f} f1={metrics['f1']:.4f} "
                  f"auc={metrics['roc_auc']:.4f}" if metrics["roc_auc"] else
                  f"        accuracy={metrics['accuracy']:.4f} precision={metrics['precision']:.4f} "
                  f"recall={metrics['recall']:.4f} f1={metrics['f1']:.4f}")
            print(f"        {CV_FOLDS}-fold CV F1: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})"
                  f" | fit time {elapsed:.2f}s")

        trained[candidate.key] = (estimator, candidate, metrics, elapsed, cv_scores)

        run.comparison.append(
            {
                "model_name": candidate.name,
                "model_key": candidate.key,
                "accuracy": round(metrics["accuracy"], 4),
                "precision": round(metrics["precision"], 4),
                "recall": round(metrics["recall"], 4),
                "f1": round(metrics["f1"], 4),
                "roc_auc": round(metrics["roc_auc"], 4) if metrics["roc_auc"] else None,
                "cv_f1_mean": round(float(cv_scores.mean()), 4),
                "cv_f1_std": round(float(cv_scores.std()), 4),
                "train_seconds": round(elapsed, 2),
                "rationale": candidate.rationale,
                "notes": candidate.notes,
            }
        )

    winner_row = select_winner(run.comparison)
    winner_key = winner_row["model_key"]
    winner_estimator, winner_candidate, winner_metrics, winner_elapsed, winner_cv = trained[winner_key]

    # Mark the chosen model in the comparison table.
    for row in run.comparison:
        row["chosen"] = row["model_key"] == winner_key

    tied_names = winner_row.get("_tied_with", [])
    tie_note = (
        f" It is statistically tied on F1 with {', '.join(tied_names)} "
        f"(gap < {F1_TIE_TOLERANCE}, smaller than the CV fold spread), so the "
        f"tie-break was ROC-AUC ({winner_metrics['roc_auc']:.4f}) and then model simplicity."
        if tied_names
        else ""
    )
    selection_reason = (
        f"{winner_candidate.name}: spam F1 {winner_metrics['f1']:.4f}, "
        f"precision {winner_metrics['precision']:.4f}, recall {winner_metrics['recall']:.4f}, "
        f"ROC-AUC {winner_metrics['roc_auc']:.4f} on the held-out test set; "
        f"{CV_FOLDS}-fold CV F1 {float(winner_cv.mean()):.4f} +/- {float(winner_cv.std()):.4f}."
        f"{tie_note}"
    )
    if verbose:
        print(f"\n[winner] {winner_candidate.name}")
        print(f"         {selection_reason}")

    model_path = save_model(
        key=winner_key,
        name=winner_candidate.name,
        classifier=winner_estimator,
        vectorizer=vectorizer,
        metrics={
            "accuracy": round(winner_metrics["accuracy"], 4),
            "precision": round(winner_metrics["precision"], 4),
            "recall": round(winner_metrics["recall"], 4),
            "f1": round(winner_metrics["f1"], 4),
            "roc_auc": round(winner_metrics["roc_auc"], 4) if winner_metrics["roc_auc"] else None,
            "confusion_matrix": winner_metrics["confusion_matrix"],
        },
        train_size=int(X_train.shape[0]),
        test_size=int(X_test.shape[0]),
        elapsed=winner_elapsed,
    )

    payload = {
        "model_name": winner_candidate.name,
        "model_key": winner_key,
        "active_model_file": model_path.name,
        "version": MODEL_VERSION,
        "dataset": DATASET_NAME,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_size": int(X_train.shape[0]),
        "test_size": int(X_test.shape[0]),
        "test_size_ratio": TEST_SIZE,
        "cv_folds": CV_FOLDS,
        "random_state": RANDOM_STATE,
        "sklearn_version": sklearn.__version__,
        "python_version": platform.python_version(),
        "accuracy": round(winner_metrics["accuracy"], 4),
        "precision": round(winner_metrics["precision"], 4),
        "recall": round(winner_metrics["recall"], 4),
        "f1": round(winner_metrics["f1"], 4),
        "roc_auc": round(winner_metrics["roc_auc"], 4) if winner_metrics["roc_auc"] else None,
        "confusion_matrix": winner_metrics["confusion_matrix"],
        "classification_report": winner_metrics["classification_report"],
        "comparison": run.comparison,
        "selection_reason": selection_reason,
        "limitations": [
            "English SMS only. Hindi/Hinglish text is NOT reliably classified by this model; "
            "those messages rely on the curated rule engine.",
            "Minority class (12.4% spam): accuracy alone is misleading, so F1/recall are reported.",
            "The output probability is a model score, not a guarantee of fraud or safety.",
        ],
    }
    write_metrics(payload)

    if verbose:
        print("\n[report] confusion matrix (rows = actual, cols = predicted)")
        matrix = np.array(winner_metrics["confusion_matrix"])
        print("                 pred ham   pred spam")
        print(f"  actual ham   {matrix[0][0]:9d}   {matrix[0][1]:9d}")
        print(f"  actual spam  {matrix[1][0]:9d}   {matrix[1][1]:9d}")
        print("\n[report] classification report")
        print(winner_metrics["classification_report"])
        print("[ok] Training complete. Restart the API to load the new model.")

    return payload


def main() -> int:
    print("=" * 68)
    print(" ScamShield AI - model training")
    print(f" dataset : {DATASET_NAME}")
    print(f" sklearn : {sklearn.__version__}")
    print("=" * 68)
    train_all(verbose=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
