"""
ScamShield AI - frontend/components/result_view.py
==================================================
Renders one ScanResponse.

This is the most important UI file in the project, because it decides how
honestly the system presents itself. Layout:

  1. Verdict banner   - risk level, score, headline
  2. Three columns    - rule engine | ML model | URL analysis  (kept SEPARATE)
  3. Explanation      - Gemini narrative or deterministic fallback
  4. Recommended actions
  5. Technical detail - expandable, for the viva

Rules followed here:
  * Never merge the ML percentage into the risk score visually.
  * Always show the disclaimer.
  * Show the *matched text*, so the user can audit the rule themselves.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List

import streamlit as st

from frontend.components import ui

RISK_COLOURS = {
    "low": "#22c55e",
    "medium": "#f59e0b",
    "high": "#f97316",
    "critical": "#ef4444",
}


def _verdict_banner(result: Dict[str, Any]) -> None:
    risk = result["risk"]
    level = risk["level"]
    colour = RISK_COLOURS.get(level, "#22d3ee")

    st.markdown(
        f"""
        <div class="ss-card" style="border-left:5px solid {colour};">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;">
            <div>
              <div class="ss-card-label">Verdict</div>
              <div style="font-size:1.5rem;font-weight:700;color:{colour};margin-top:4px;">
                {html.escape(risk['headline'])}
              </div>
              <div class="ss-card-foot">
                Risk level {ui.risk_pill(level)} &nbsp;·&nbsp; score {risk['score']}/100
                &nbsp;·&nbsp; processed in {result.get('processing_ms', 0)} ms
              </div>
            </div>
            <div style="text-align:right;">
              <div class="ss-card-label">Scan ID</div>
              <div class="ss-mono" style="margin-top:6px;">{result['scan_id'][:16]}…</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    ui.risk_meter(risk["score"], level)


def _layer_columns(result: Dict[str, Any]) -> None:
    """Rules | ML | URLs, side by side and clearly independent."""
    rule_col, ml_col, url_col = st.columns(3, gap="medium")

    # ---------------- rule engine -------------------------------------
    with rule_col:
        rules = result["rule_engine"]
        ui.section_title("1 · Rule engine")
        st.markdown(
            f"**Score {rules['score']}/100** · {rules['matched_count']} rule(s) matched"
        )
        if not rules["findings"]:
            st.caption("No rules triggered.")
        for finding in rules["findings"][:6]:
            ui.finding_row(
                finding["title"],
                finding["description"],
                finding.get("matched_text", []),
                finding["severity"],
            )
        if rules["matched_count"] > 6:
            with st.expander(f"Show all {rules['matched_count']} findings"):
                for finding in rules["findings"][6:]:
                    ui.finding_row(
                        finding["title"],
                        finding["description"],
                        finding.get("matched_text", []),
                        finding["severity"],
                    )

    # ---------------- ML model ----------------------------------------
    with ml_col:
        ml = result["ml_prediction"]
        ui.section_title("2 · ML classifier")
        if not ml["available"]:
            st.warning("Model not available")
            st.caption(ml.get("note", ""))
        else:
            probability = ml.get("spam_probability")
            if probability is None:
                st.info(ml.get("note", "No score."))
            else:
                colour = "#f97316" if probability >= ml["threshold"] else "#22c55e"
                st.markdown(
                    f"""
                    <div class="ss-card">
                      <div class="ss-card-label">Estimated spam probability</div>
                      <div class="ss-card-value" style="color:{colour};">{probability:.1%}</div>
                      <div class="ss-card-foot">
                        label <b>{html.escape(ml['label'])}</b> ·
                        threshold {ml['threshold']} ·
                        {html.escape((ml.get('model') or {}).get('name', 'n/a'))}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.progress(min(1.0, float(probability)))
                st.caption(ml.get("note", ""))

    # ---------------- URL analysis ------------------------------------
    with url_col:
        urls = result["urls"]
        ui.section_title("3 · URL analysis")
        if not urls["analyses"]:
            st.caption("No links found in this message.")
        for analysis in urls["analyses"]:
            score = analysis["score"]
            colour = (
                "#ef4444" if score >= 70 else "#f97316" if score >= 45
                else "#f59e0b" if score >= 20 else "#22c55e"
            )
            st.markdown(
                f"""
                <div class="ss-card" style="margin-bottom:10px;">
                  <div class="ss-card-label">URL score</div>
                  <div class="ss-card-value" style="color:{colour};font-size:1.25rem;">
                    {score}/100
                  </div>
                  <div class="ss-mono" style="word-break:break-all;margin-top:4px;">
                    {html.escape(analysis['hostname'] or analysis['raw'])[:70]}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            for indicator in analysis["indicators"][:5]:
                ui.finding_row(
                    indicator["label"], indicator["detail"], [], indicator["severity"]
                )
            if not analysis["indicators"]:
                st.caption("No URL red flags detected (this is not a safety guarantee).")


def _explanation_block(result: Dict[str, Any]) -> None:
    explanation = result["explanation"]
    ui.section_title("Explanation & guidance")

    badge = {
        "gemini": ("Generated by Gemini", "🟣"),
        "fallback": ("Automated explanation (Gemini not used)", "⚙️"),
        "disabled": ("Explanation disabled for this scan", "🚫"),
        "error": ("Explanation unavailable", "⚠️"),
    }.get(explanation.get("source", "fallback"), ("Explanation", "ℹ️"))

    st.markdown(f"**{badge[1]} {badge[0]}**")
    if explanation.get("summary"):
        st.write(explanation["summary"])

    left, right = st.columns(2, gap="medium")
    with left:
        if explanation.get("suspicious_elements"):
            st.markdown("**Suspicious elements**")
            for element in explanation["suspicious_elements"]:
                st.markdown(f"- {element}")
        if explanation.get("scam_techniques"):
            st.markdown("**Likely scam techniques**")
            for technique in explanation["scam_techniques"]:
                st.markdown(f"- {technique}")
    with right:
        actions = explanation.get("recommendations") or result["risk"]["recommended_actions"]
        if actions:
            st.markdown("**What you should do**")
            for action in actions:
                st.markdown(f"- {action}")

    if explanation.get("error"):
        st.caption(f"Reason: {explanation['error']}")
    if explanation.get("disclaimer"):
        st.caption(explanation["disclaimer"])


def _technical_detail(result: Dict[str, Any]) -> None:
    with st.expander("Technical detail (for review / viva)"):
        st.markdown("**Risk fusion reasons**")
        for reason in result["risk"]["reasons"]:
            st.markdown(f"- {reason}")

        st.markdown("**Component scores**")
        st.json(
            {
                "rule_score": result["risk"]["rule_score"],
                "ml_spam_probability": result["risk"]["ml_score"],
                "url_highest_score": result["urls"]["highest_score"],
                "final_score": result["risk"]["score"],
                "risk_level": result["risk"]["level"],
                "scan_type": result["scan_type"],
                "processing_ms": result["processing_ms"],
            }
        )

        st.markdown("**Privacy: what was stored**")
        st.code(result.get("input_preview", ""), language="text")
        st.caption(
            "Phone numbers, emails, card numbers and OTP values are redacted before "
            "storage and before being sent to any external AI service."
        )


def render(result: Dict[str, Any], *, show_technical: bool = True) -> None:
    """Render a complete scan result."""
    _verdict_banner(result)
    st.write("")
    _layer_columns(result)
    st.write("")
    _explanation_block(result)
    st.write("")
    ui.disclaimer_box()
    if show_technical:
        _technical_detail(result)


def render_compact_row(result: Dict[str, Any]) -> None:
    """One-line summary used in lists (batch results, history preview)."""
    risk = result["risk"]
    colour = RISK_COLOURS.get(risk["level"], "#22d3ee")
    st.markdown(
        f"""
        <div class="ss-finding" style="border-left-color:{colour};">
          <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;">
            <div class="ss-finding-title">{html.escape(result.get('input_preview', '')[:90])}</div>
            <div>{ui.risk_pill(risk['level'])} <span class="ss-mono">{risk['score']}/100</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_loading_note() -> None:
    st.caption(
        "Analysis combines the rule engine, the ML model, URL pattern checks and "
        "optionally Gemini. A first call may take ~1s while the model is loaded."
    )
