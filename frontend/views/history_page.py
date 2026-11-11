"""
ScamShield AI - frontend/views/history_page.py
==============================================
Scan history with filtering, detail view, deletion and CSV export.

Privacy behaviour
-----------------
* Only the redacted preview is displayed by default; raw text is never shown.
* "Clear all history" requires an explicit confirmation checkbox.
* Individual scans can be deleted.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from frontend import api_client
from frontend.components import result_view, ui

RISK_FILTERS = ["all", "low", "medium", "high", "critical"]
TYPE_FILTERS = ["all", "message", "email", "url"]


def _table(items: list) -> None:
    """Render history rows as a styled HTML table."""
    rows = []
    for item in items:
        rows.append(
            f"""
            <tr>
              <td class="ss-mono" style="white-space:nowrap;">{item['created_at'][:19].replace('T', ' ')}</td>
              <td>{html.escape(item['scan_type'])}</td>
              <td>{ui.risk_pill(item['risk_level'])}</td>
              <td style="text-align:right;" class="ss-mono">{item['risk_score']}</td>
              <td style="text-align:right;" class="ss-mono">{item['rule_score']}</td>
              <td class="ss-mono">{html.escape(item['ml_label'])}</td>
              <td>{html.escape(item.get('message_preview', '')[:90])}</td>
            </tr>
            """
        )
    st.markdown(
        f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.84rem;">
          <thead>
            <tr style="color:#96a7c4;text-align:left;border-bottom:1px solid #24344f;">
              <th style="padding:8px 6px;">When (UTC)</th>
              <th style="padding:8px 6px;">Type</th>
              <th style="padding:8px 6px;">Risk</th>
              <th style="padding:8px 6px;text-align:right;">Risk score</th>
              <th style="padding:8px 6px;text-align:right;">Rule score</th>
              <th style="padding:8px 6px;">ML label</th>
              <th style="padding:8px 6px;">Preview (redacted)</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


def render() -> None:
    st.subheader("Scan history")
    st.caption(
        "Stored locally in SQLite. Personal data (phone numbers, emails, card numbers, "
        "OTP values) is redacted before storage."
    )

    # ---------------- filters -----------------------------------------
    col1, col2, col3, col4 = st.columns([1, 1, 2, 1])
    with col1:
        risk_filter = st.selectbox("Risk level", RISK_FILTERS)
    with col2:
        type_filter = st.selectbox("Type", TYPE_FILTERS)
    with col3:
        search = st.text_input("Search preview", placeholder="e.g. KYC, lottery")
    with col4:
        page_size = st.selectbox("Rows per page", [10, 25, 50], index=1)

    page = st.number_input("Page", min_value=1, value=1, step=1)

    try:
        history = api_client.get_history(
            page=int(page),
            page_size=int(page_size),
            risk_level=None if risk_filter == "all" else risk_filter,
            scan_type=None if type_filter == "all" else type_filter,
            search=search or None,
        )
    except api_client.APIError as exc:
        st.error(f"Could not load history: {exc}")
        return

    if not history["items"]:
        st.info("No scans match these filters.")
    else:
        _table(history["items"])
        st.caption(
            f"Showing {len(history['items'])} of {history['total']} · "
            f"page {history['page']}"
            + (" · more pages available" if history["has_more"] else " · last page")
        )

    st.divider()

    # ---------------- detail / delete ---------------------------------
    left, right = st.columns(2, gap="medium")
    with left:
        ui.section_title("Inspect a scan")
        if history["items"]:
            options = {
                f"{item['created_at'][:19]} · {item['risk_level']} · {item['scan_id'][:8]}": item["scan_id"]
                for item in history["items"]
            }
            chosen_label = st.selectbox("Select scan", list(options.keys()))
            if st.button("Open detail"):
                try:
                    record = api_client.get_history_item(options[chosen_label])
                    st.session_state["history_detail"] = record
                except api_client.APIError as exc:
                    st.error(str(exc))

            detail = st.session_state.get("history_detail")
            if detail:
                st.markdown("**Stored findings**")
                for finding in detail.get("rule_findings", [])[:8]:
                    ui.finding_row(
                        finding.get("title", ""),
                        finding.get("description", ""),
                        finding.get("matched_text", []),
                        finding.get("severity", "medium"),
                    )
                st.markdown("**Redacted text**")
                st.code(detail.get("message_redacted", "—"), language="text")
                st.caption(f"Stored at {detail.get('created_at', '')}")

    with right:
        ui.section_title("Manage & export")
        try:
            export = api_client.export_history_csv()
        except api_client.APIError:
            export = ""
        st.download_button(
            "⬇️ Export history as CSV",
            data=export if isinstance(export, str) else "",
            file_name="scamshield_history.csv",
            mime="text/csv",
            width="stretch",
        )

        st.write("")
        confirm = st.checkbox("I understand this permanently deletes all scan history")
        if st.button("🗑️ Clear all history", disabled=not confirm, width="stretch"):
            try:
                response = api_client.clear_history()
                st.success(response.get("message", "History cleared."))
                st.session_state.pop("history_detail", None)
                st.rerun()
            except api_client.APIError as exc:
                st.error(str(exc))

        if st.button("Delete the selected scan", width="stretch"):
            detail = st.session_state.get("history_detail")
            if not detail:
                st.warning("Open a scan detail first.")
            else:
                try:
                    api_client.delete_history_item(detail["scan_id"])
                    st.success("Scan deleted.")
                    st.session_state.pop("history_detail", None)
                    st.rerun()
                except api_client.APIError as exc:
                    st.error(str(exc))
