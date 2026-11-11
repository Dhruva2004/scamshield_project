"""
ScamShield AI - frontend/components/ui.py
=========================================
Reusable HTML/CSS building blocks for the Streamlit UI.

Why this file exists
--------------------
Streamlit's built-in widgets are functional but look generic. To get a
professional cybersecurity dashboard we render small HTML fragments with
`st.markdown(..., unsafe_allow_html=True)`.

Keeping them in one module means:
  * one place to change colours/markup,
  * pages stay readable (they call `metric_card(...)`, not 20 lines of HTML),
  * every fragment escapes user text with `html.escape` (XSS-safe).
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

RISK_COLORS = {
    "low": "#22c55e",
    "medium": "#f59e0b",
    "high": "#f97316",
    "critical": "#ef4444",
}

RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}

STYLESHEET = Path(__file__).resolve().parent.parent / "styles" / "theme.css"


def _sanitise_css_for_markdown(css: str) -> str:
    """
    Make a stylesheet safe to pass through Streamlit's Markdown renderer.

    THE BUG THIS FIXES
    ------------------
    `st.markdown("<style>...</style>")` runs the CSS through a CommonMark parser
    *before* the browser sees it. CommonMark ends a raw HTML block at a blank line
    and treats a line starting with '#' as a heading. Our theme contained the
    comment line "Colours: deep navy (#0b1220)..." - that '#' was enough to close
    the <style> block, so the remaining ~8 KB of CSS rendered as 30 visible
    paragraphs of text and none of the styling applied.

    Two transformations, both no-ops for valid CSS:
      1. Strip comments (not needed at runtime).
      2. Collapse all whitespace so no line can start with '#' and no blank line
         can terminate the HTML block.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"\s+", " ", css)
    return css.strip()


def inject_theme() -> None:
    """Load frontend/styles/theme.css into the page exactly once."""
    if st.session_state.get("_ss_theme_loaded"):
        return
    css = _sanitise_css_for_markdown(STYLESHEET.read_text(encoding="utf-8"))
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    st.session_state["_ss_theme_loaded"] = True


def header(title: str = "ScamShield AI", subtitle: str = "") -> None:
    """Branded page header."""
    st.markdown(
        f"""
        <div class="ss-header">
          <div class="ss-logo">🛡️</div>
          <div>
            <p class="ss-title">{html.escape(title)}</p>
            <p class="ss-subtitle">{html.escape(subtitle)}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value, foot: str = "", colour: Optional[str] = None) -> str:
    """Return the HTML for one dashboard metric card."""
    value_style = f"color:{colour};" if colour else ""
    return f"""
    <div class="ss-card">
      <div class="ss-card-label">{html.escape(str(label))}</div>
      <div class="ss-card-value" style="{value_style}">{html.escape(str(value))}</div>
      <div class="ss-card-foot">{html.escape(str(foot))}</div>
    </div>
    """


def render_metric_row(cards: List[Dict]) -> None:
    """
    Render a responsive row of metric cards.

    Pass a list of dicts: {"label": ..., "value": ..., "foot": ..., "colour": ...}
    """
    columns = st.columns(len(cards), gap="small")
    for column, card in zip(columns, cards):
        with column:
            st.markdown(
                metric_card(
                    card.get("label", ""),
                    card.get("value", "—"),
                    card.get("foot", ""),
                    card.get("colour"),
                ),
                unsafe_allow_html=True,
            )


def risk_pill(level: str) -> str:
    """Coloured pill: LOW / MEDIUM / HIGH / CRITICAL."""
    level_clean = (level or "low").lower()
    return (
        f'<span class="ss-pill ss-pill-{level_clean}">'
        f"{RISK_EMOJI.get(level_clean, '')} {level_clean.upper()}</span>"
    )


def risk_meter(score: int, level: str) -> None:
    """Horizontal 0-100 gauge coloured by risk level."""
    score = max(0, min(100, int(score)))
    colour = RISK_COLORS.get((level or "low").lower(), "#22d3ee")
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:12px;">
          <div class="ss-meter" style="flex:1;">
            <div class="ss-meter-fill" style="width:{score}%;background:{colour};"></div>
          </div>
          <div style="font-weight:700;color:{colour};min-width:58px;text-align:right;">
            {score}/100
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def finding_row(title: str, description: str = "", matches: Optional[List[str]] = None,
                severity: str = "medium") -> None:
    """One triggered rule / indicator, with colour-coded left border."""
    colour = RISK_COLORS.get(severity, "#22d3ee")
    match_html = ""
    if matches:
        joined = " · ".join(html.escape(str(m)) for m in matches[:4])
        match_html = f'<div class="ss-finding-match">matched: {joined}</div>'
    st.markdown(
        f"""
        <div class="ss-finding" style="border-left-color:{colour};">
          <div class="ss-finding-title">{html.escape(title)}</div>
          <div class="ss-finding-desc">{html.escape(description)}</div>
          {match_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f'<div class="ss-section-title">{html.escape(text)}</div>', unsafe_allow_html=True)


def divider() -> None:
    st.markdown('<div class="ss-divider"></div>', unsafe_allow_html=True)


def note(text: str) -> None:
    """Muted explanatory paragraph."""
    st.markdown(f'<p class="ss-muted" style="font-size:0.85rem;">{html.escape(text)}</p>',
                unsafe_allow_html=True)


def disclaimer_box() -> None:
    """The legal/honesty disclaimer shown on results pages."""
    st.info(
        "**Guidance, not guarantees.** ScamShield AI combines explainable rules with a "
        "statistical model trained on SMS data. It can be wrong in both directions. "
        "Never share OTPs, PINs or passwords, and verify any request through the "
        "official bank/app channel."
    )
