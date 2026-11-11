"""
ScamShield AI - frontend/views/dashboard.py
===========================================
The main cybersecurity dashboard.

Layout
------
Row 1  KPI cards        (scans, spam, suspicious URLs, high-risk)
Row 2  Charts           (risk donut, activity trend)
Row 3  Indicators + model performance
Row 4  Recent scan history

Everything comes from the API, so the dashboard reflects real stored data -
including the model metrics that were actually measured during training.
"""

from __future__ import annotations

import html

import streamlit as st

from frontend import api_client
from frontend.components import charts, ui

RISK_COLOURS = {
    "low": "#22c55e",
    "medium": "#f59e0b",
    "high": "#f97316",
    "critical": "#ef4444",
}


def _kpi_row(stats: dict) -> None:
    ui.render_metric_row(
        [
            {
                "label": "Messages analysed",
                "value": f"{stats.get('total_scans', 0):,}",
                "foot": "all time",
                "colour": "#4f8cff",
            },
            {
                "label": "Spam detected",
                "value": f"{stats.get('spam_detected', 0):,}",
                "foot": "ML label = spam",
                "colour": "#f97316",
            },
            {
                "label": "Suspicious URLs",
                "value": f"{stats.get('suspicious_urls', 0):,}",
                "foot": "URL score ≥ 40",
                "colour": "#22d3ee",
            },
            {
                "label": "High / critical",
                "value": f"{stats.get('high_risk_scans', 0):,}",
                "foot": "needs attention",
                "colour": "#ef4444",
            },
        ]
    )


def _model_panel(stats: dict) -> None:
    performance = stats.get("model_performance", {})
    ui.section_title("Model performance")
    if not performance.get("available"):
        st.warning("No trained model found. Run `python scripts/train_models.py`.")
        return

    ui.render_metric_row(
        [
            {"label": "Algorithm", "value": performance.get("model_name", "—"), "foot": "active artefact"},
            {"label": "Accuracy", "value": f"{performance.get('accuracy', 0):.2%}", "foot": "held-out test set", "colour": "#22d3ee"},
            {"label": "Precision (spam)", "value": f"{performance.get('precision', 0):.2%}", "foot": "alarm is right", "colour": "#a78bfa"},
            {"label": "Recall (spam)", "value": f"{performance.get('recall', 0):.2%}", "foot": "scams caught", "colour": "#22c55e"},
            {"label": "F1", "value": f"{performance.get('f1', 0):.3f}", "foot": "precision/recall balance", "colour": "#f59e0b"},
        ]
    )

    matrix = performance.get("confusion_matrix")
    if matrix:
        st.caption(
            f"Dataset: {performance.get('dataset', 'UCI SMS Spam Collection')} · "
            f"trained {str(performance.get('trained_at', ''))[:10]} · "
            f"confusion matrix [[TN {matrix[0][0]}, FP {matrix[0][1]}], "
            f"[FN {matrix[1][0]}, TP {matrix[1][1]}]]"
        )
        try:
            comparison = api_client.get_model_comparison()
            if comparison.get("available"):
                st.altair_chart(charts.model_metrics_chart(comparison["entries"]), width="stretch")
                with st.expander("Why this algorithm was selected"):
                    st.write(comparison.get("selection_reason", ""))
        except api_client.APIError:
            pass


def _recent_scans() -> None:
    ui.section_title("Recent scans")
    try:
        history = api_client.get_history(page=1, page_size=8)
    except api_client.APIError as exc:
        st.error(f"Could not load history: {exc}")
        return

    if not history["items"]:
        st.info("No scans yet. Go to **Message Analyser** and analyse a message.")
        return

    rows = "".join(
        f"""
        <tr>
          <td class="ss-mono">{item['created_at'][:19].replace('T', ' ')}</td>
          <td>{html.escape(item['scan_type'])}</td>
          <td>{ui.risk_pill(item['risk_level'])}</td>
          <td style="text-align:right;" class="ss-mono">{item['risk_score']}</td>
          <td>{html.escape(item.get('message_preview', '')[:80])}</td>
        </tr>
        """
        for item in history["items"]
    )
    st.markdown(
        f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
          <thead>
            <tr style="color:#96a7c4;text-align:left;border-bottom:1px solid #24344f;">
              <th style="padding:8px 6px;">When (UTC)</th>
              <th style="padding:8px 6px;">Type</th>
              <th style="padding:8px 6px;">Risk</th>
              <th style="padding:8px 6px;text-align:right;">Score</th>
              <th style="padding:8px 6px;">Preview (redacted)</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )
    st.caption(f"{history['total']} scan(s) stored. Full list on the History page.")


def render() -> None:
    st.subheader("Security dashboard")

    try:
        stats = api_client.get_stats()
    except api_client.APIError as exc:
        st.error(f"Could not reach the ScamShield API: {exc}")
        st.info(
            "Start the backend first:\n\n"
            "```\nuvicorn backend.main:app --reload --port 8000\n```"
        )
        return

    _kpi_row(stats)
    st.write("")

    distribution = stats.get("risk_distribution", {})
    left, right = st.columns([1, 1.4], gap="medium")
    with left:
        st.altair_chart(charts.risk_donut(distribution), width="stretch")
    with right:
        st.altair_chart(charts.daily_trend(stats.get("daily_counts", [])), width="stretch")

    if stats.get("total_scans", 0) == 0:
        st.info(
            "No data yet. Analyse a message to populate the dashboard — "
            "the charts fill in automatically."
        )

    st.divider()
    left, right = st.columns([1.2, 1], gap="medium")
    with left:
        st.altair_chart(charts.indicators_bar(stats.get("top_indicators", [])), width="stretch")
    with right:
        st.altair_chart(charts.risk_bar(distribution), width="stretch")
        if stats.get("average_risk_score") is not None:
            st.caption(f"Average risk score across all scans: {stats['average_risk_score']}/100")

    st.divider()
    _model_panel(stats)

    st.divider()
    _recent_scans()
