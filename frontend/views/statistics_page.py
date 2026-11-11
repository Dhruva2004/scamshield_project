"""
ScamShield AI - frontend/views/statistics_page.py
=================================================
Deep-dive statistics, model transparency and detection-quality discussion.

This page exists because a reviewer will ask: "how do you know it works?"
It answers with measured numbers, the confusion matrix, the algorithm
comparison, the top learned terms, and an explicit limitations table.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend import api_client
from frontend.components import charts, result_view, ui


def _model_section() -> None:
    st.markdown("### Machine-learning model")
    try:
        comparison = api_client.get_model_comparison()
    except api_client.APIError as exc:
        st.error(f"Could not load model comparison: {exc}")
        return

    if not comparison.get("available"):
        st.warning(comparison.get("selection_reason", "No metrics available."))
        return

    st.caption(f"Dataset: {comparison.get('dataset')} · trained {comparison.get('trained_at', '')[:19]}")

    frame = pd.DataFrame(comparison["entries"])
    frame = frame.rename(
        columns={
            "model_name": "Model", "accuracy": "Accuracy", "precision": "Precision",
            "recall": "Recall", "f1": "F1", "roc_auc": "ROC-AUC",
            "train_seconds": "Train (s)", "chosen": "Selected",
        }
    )
    st.dataframe(
        frame[["Model", "Accuracy", "Precision", "Recall", "F1", "ROC-AUC", "Train (s)", "Selected"]],
        width="stretch",
        hide_index=True,
        column_config={
            "Accuracy": st.column_config.NumberColumn(format="%.4f"),
            "Precision": st.column_config.NumberColumn(format="%.4f"),
            "Recall": st.column_config.NumberColumn(format="%.4f"),
            "F1": st.column_config.NumberColumn(format="%.4f"),
            "ROC-AUC": st.column_config.NumberColumn(format="%.4f"),
            "Train (s)": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.altair_chart(charts.model_metrics_chart(comparison["entries"]), width="stretch")

    st.info(f"**Selection rule.** {comparison.get('selection_reason')}")
    st.caption(
        f"Vectorizer: {comparison.get('vectorizer')} · "
        f"cross-validation: {comparison.get('cross_validation', {}).get('folds')} folds"
    )


def _terms_section() -> None:
    st.markdown("### What the model learned")
    try:
        terms = api_client.get_model_terms(top_k=20)
    except api_client.APIError:
        return
    if not terms.get("available"):
        st.caption(terms.get("reason", ""))
        return

    left, right = st.columns(2)
    with left:
        st.markdown("**Strongest spam terms**")
        st.dataframe(
            pd.DataFrame(terms["top_spam_terms"]),
            width="stretch", hide_index=True,
            column_config={"weight": st.column_config.NumberColumn(format="%.3f")},
        )
    with right:
        st.markdown("**Strongest ham terms**")
        st.dataframe(
            pd.DataFrame(terms["top_ham_terms"]),
            width="stretch", hide_index=True,
            column_config={"weight": st.column_config.NumberColumn(format="%.3f")},
        )
    st.caption(terms.get("note", ""))


def render() -> None:
    st.subheader("Statistics & model transparency")

    try:
        stats = api_client.get_stats()
    except api_client.APIError as exc:
        st.error(f"Could not load statistics: {exc}")
        return

    ui.render_metric_row(
        [
            {"label": "Total scans", "value": stats.get("total_scans", 0), "foot": "stored"},
            {"label": "Avg risk score", "value": stats.get("average_risk_score", "—"), "foot": "0–100"},
            {"label": "Spam (ML)", "value": stats.get("spam_detected", 0), "foot": "labelled spam"},
            {"label": "High/critical", "value": stats.get("high_risk_scans", 0), "foot": "needs attention"},
        ]
    )
    st.write("")

    left, right = st.columns(2, gap="medium")
    with left:
        st.altair_chart(charts.risk_donut(stats.get("risk_distribution", {})), width="stretch")
    with right:
        st.altair_chart(charts.risk_bar(stats.get("risk_distribution", {})), width="stretch")

    st.altair_chart(charts.daily_trend(stats.get("daily_counts", [])), width="stretch")
    st.altair_chart(charts.indicators_bar(stats.get("top_indicators", [])), width="stretch")

    st.divider()
    _model_section()

    st.divider()
    _terms_section()

    st.divider()
    st.markdown("### Honest limitations")
    st.markdown(
        """
| Component | What it can do | What it cannot do |
|---|---|---|
| **Rule engine** | Catch known scam mechanics (OTP requests, KYC pressure, UPI lures) with full explanations | Recognise novel wording; a scam phrased unusually can slip through |
| **ML classifier** | Learn statistical patterns from 5,158 real SMS messages (F1 ≈ 0.94) | Handle Hindi/Hinglish reliably; judge modern UPI/KYC phrasing it never saw; give certainty |
| **URL analyser** | Flag look-alike domains, IP hosts, shorteners, punycode, executable downloads | Visit or sandbox the page; detect a legitimate-but-compromised site; prove a site is safe |
| **Gemini explainer** | Explain the verdict in EN/HI/Hinglish in friendly language | Detect anything itself; it only narrates the engines' findings |

**Bottom line:** ScamShield AI is a decision-support tool. It reduces the chance of
falling for a scam and explains the reasoning, but it is not a guarantee and it
never replaces verifying through official channels.
"""
    )

    st.divider()
    st.markdown("### Detection score distribution (explained)")
    st.caption(
        "The final score is `max(rule_score, ML_component, URL_component)` plus an "
        "agreement bonus when independent layers concur. Thresholds: LOW 0–19, "
        "MEDIUM 20–44, HIGH 45–69, CRITICAL 70–100."
    )
