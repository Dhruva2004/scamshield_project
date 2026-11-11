"""
ScamShield AI - frontend/components/charts.py
=============================================
Altair chart builders for the dashboard.

Why Altair: Streamlit ships with it (no extra dependency), it produces clean
declarative specs, and the dark theme can be set once here rather than in every
page. Every function returns a chart object, so pages stay declarative.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import altair as alt
import pandas as pd

# Shared dark palette, matching frontend/styles/theme.css
RISK_COLOURS = {
    "low": "#22c55e",
    "medium": "#f59e0b",
    "high": "#f97316",
    "critical": "#ef4444",
}
ACCENT = "#4f8cff"
ACCENT_2 = "#22d3ee"
AXIS_COLOUR = "#96a7c4"
GRID_COLOUR = "#24344f"


def _style(chart: alt.Chart) -> alt.Chart:
    """Apply the house style to any Altair chart."""
    return (
        chart.configure_view(strokeOpacity=0)
        .configure_axis(
            labelColor=AXIS_COLOUR,
            titleColor=AXIS_COLOUR,
            gridColor=GRID_COLOUR,
            domainColor=GRID_COLOUR,
        )
        .configure_legend(labelColor=AXIS_COLOUR, titleColor=AXIS_COLOUR)
    )


def risk_donut(distribution: Dict[str, int]) -> alt.Chart:
    """
    Donut chart of the risk distribution.

    A donut is used instead of a pie because the hole gives room for the total
    and the proportions remain comparable at a glance.
    """
    frame = pd.DataFrame(
        [
            {"risk": level, "count": int(distribution.get(level, 0))}
            for level in ("low", "medium", "high", "critical")
        ]
    )
    frame = frame[frame["count"] > 0]
    if frame.empty:
        frame = pd.DataFrame([{"risk": "no data", "count": 1}])

    base = alt.Chart(frame).encode(
        theta=alt.Theta("count:Q", stack=True),
        color=alt.Color(
            "risk:N",
            scale=alt.Scale(
                domain=list(RISK_COLOURS.keys()) + ["no data"],
                range=list(RISK_COLOURS.values()) + ["#24344f"],
            ),
            legend=alt.Legend(title="Risk level", orient="right"),
        ),
        tooltip=["risk:N", "count:Q"],
    )
    arcs = base.mark_arc(innerRadius=62, outerRadius=105, stroke="#0b1220", strokeWidth=2)
    return _style(arcs).properties(height=280, title="Risk distribution")


def daily_trend(daily_counts: Sequence[Dict]) -> alt.Chart:
    """Area + line chart of scans per day."""
    if not daily_counts:
        frame = pd.DataFrame([{"date": "no data", "count": 0}])
    else:
        frame = pd.DataFrame(list(daily_counts))
    frame["count"] = frame["count"].astype(int)

    area = (
        alt.Chart(frame)
        .mark_area(
            line={"color": ACCENT_2, "strokeWidth": 2},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="#22d3ee33", offset=0),
                    alt.GradientStop(color="#22d3ee00", offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
        )
        .encode(
            x=alt.X("date:N", title="Date", axis=alt.Axis(labelAngle=-40)),
            y=alt.Y("count:Q", title="Scans"),
            tooltip=["date:N", "count:Q"],
        )
    )
    return _style(area).properties(height=260, title="Scan activity (last 14 days)")


def risk_bar(distribution: Dict[str, int]) -> alt.Chart:
    """Horizontal bar chart - easier to read than a donut for small counts."""
    frame = pd.DataFrame(
        [
            {"risk": level, "count": int(distribution.get(level, 0))}
            for level in ("critical", "high", "medium", "low")
        ]
    )
    return _style(
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=6)
        .encode(
            y=alt.Y("risk:N", sort=None, title=None),
            x=alt.X("count:Q", title="Scans"),
            color=alt.Color(
                "risk:N",
                scale=alt.Scale(
                    domain=list(RISK_COLOURS.keys()), range=list(RISK_COLOURS.values())
                ),
                legend=None,
            ),
            tooltip=["risk:N", "count:Q"],
        )
    ).properties(height=200, title="Scans by risk level")


def indicators_bar(top_indicators: Sequence[Dict]) -> alt.Chart:
    """Most frequently triggered indicators."""
    if not top_indicators:
        frame = pd.DataFrame([{"name": "no data yet", "count": 0}])
    else:
        frame = pd.DataFrame(list(top_indicators))
        frame["name"] = frame["name"].astype(str).str.slice(0, 46)

    return _style(
        alt.Chart(frame.head(10))
        .mark_bar(cornerRadiusEnd=6, color=ACCENT)
        .encode(
            y=alt.Y("name:N", sort="-x", title=None),
            x=alt.X("count:Q", title="Times triggered"),
            tooltip=["name:N", "count:Q"],
        )
    ).properties(height=max(220, 26 * len(frame.head(10))), title="Top triggered indicators")


def model_metrics_chart(entries: Sequence[Dict]) -> alt.Chart:
    """
    Grouped bar chart comparing models across the four headline metrics.

    Long-form data (metric, model, value) is required for Altair's grouping.
    """
    rows: List[Dict] = []
    for entry in entries:
        for metric in ("accuracy", "precision", "recall", "f1"):
            value = entry.get(metric)
            if value is not None:
                rows.append(
                    {"model": entry["model_name"], "metric": metric.upper(), "value": float(value)}
                )
    if not rows:
        return _style(alt.Chart(pd.DataFrame([{"model": "-", "metric": "-", "value": 0}]))
                      .mark_bar().encode(x="model:N", y="value:Q"))

    frame = pd.DataFrame(rows)
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("metric:N", title=None, axis=alt.Axis(labelAngle=0)),
            xOffset="model:N",
            y=alt.Y("value:Q", title="Score", scale=alt.Scale(domain=[0.85, 1.0])),
            color=alt.Color(
                "model:N",
                scale=alt.Scale(range=[ACCENT, ACCENT_2, "#a78bfa"]),
                legend=alt.Legend(title="Model", orient="top"),
            ),
            tooltip=["model:N", "metric:N", alt.Tooltip("value:Q", format=".4f")],
        )
    )
    return _style(chart).properties(
        height=300,
        title="Algorithm comparison (y-axis starts at 0.85 to show small differences)",
    )


def confidence_gauge(probability: float) -> alt.Chart:
    """Bar showing the ML spam probability with the 0.5 decision boundary."""
    frame = pd.DataFrame([{"label": "P(spam)", "value": float(probability)}])
    bars = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=8, height=26)
        .encode(
            x=alt.X("value:Q", scale=alt.Scale(domain=[0, 1]), title="Model score"),
            color=alt.condition(
                alt.datum.value >= 0.5,
                alt.value("#f97316"),
                alt.value("#22c55e"),
            ),
            tooltip=[alt.Tooltip("value:Q", format=".3f")],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame([{"x": 0.5}]))
        .mark_rule(color="#e8eefc", strokeDash=[5, 4], strokeWidth=2)
        .encode(x="x:Q")
    )
    return _style((bars + rule).properties(height=90, title=None))
