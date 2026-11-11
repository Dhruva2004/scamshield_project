"""
ScamShield AI - frontend/views/analyser.py
==========================================
The Message Analyser page.

Flow
----
pick a demo sample  ->  type/paste a message  ->  choose language  ->  Analyse
                    ->  result rendered by components/result_view.py

Notes
-----
* The sample list comes from the API, not from hard-coded strings, so the
  demo and the slides can never disagree.
* Results are cached in session_state so switching pages does not lose them.
"""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from frontend import api_client
from frontend.components import result_view, ui

SAMPLE_KEY = "analyser_text"
RESULT_KEY = "analyser_result"

LANGUAGE_OPTIONS = {
    "English": "en",
    "हिन्दी (Hindi)": "hi",
    "Hinglish": "hinglish",
}


def _load_samples() -> List[Dict[str, Any]]:
    try:
        return api_client.get_samples()
    except api_client.APIError:
        return []


def _sample_picker(samples: List[Dict[str, Any]]) -> None:
    """Buttons that prefill the textbox, grouped by category."""
    if not samples:
        return
    with st.expander("Try a demo example", expanded=False):
        st.caption(
            "These are real-world scam patterns. Each one is labelled with the risk level "
            "the system is expected to produce."
        )
        columns = st.columns(3, gap="small")
        for index, sample in enumerate(samples):
            with columns[index % 3]:
                if st.button(
                    f"{sample['label']}",
                    key=f"sample_{sample['id']}",
                    width="stretch",
                ):
                    st.session_state[SAMPLE_KEY] = sample["text"]
                    st.session_state[RESULT_KEY] = None
                    st.rerun()


def render() -> None:
    st.subheader("Message Analyser")
    st.caption(
        "Paste an SMS, WhatsApp message, email or social-media DM. "
        "Nothing is sent anywhere except your own ScamShield backend "
        "(and, if enabled, Gemini — with personal data redacted first)."
    )

    samples = _load_samples()
    _sample_picker(samples)

    left, right = st.columns([3, 1], gap="medium")

    with right:
        language_label = st.selectbox("Explanation language", list(LANGUAGE_OPTIONS.keys()))
        language = LANGUAGE_OPTIONS[language_label]
        include_explanation = st.toggle(
            "Generate explanation", value=True,
            help="Turn off to save time/quota. Detection still runs.",
        )
        scan_type = st.selectbox(
            "Input type",
            ["auto", "message", "email", "url"],
            help="'auto' detects a bare URL and treats anything else as a message.",
        )

    with left:
        text = st.text_area(
            "Message",
            key=SAMPLE_KEY,
            height=190,
            placeholder=(
                "Example: Dear Customer, your SBI KYC is suspended. "
                "Update at http://sbi-kyc-verify.xyz/login within 24 hours."
            ),
        )
        analyse = st.button("🔍 Analyse message", type="primary", width="stretch")
        result_view.render_loading_note()

    if analyse:
        if not text or not text.strip():
            st.warning("Please paste a message first.")
        else:
            with st.spinner("Analysing with rules, model and URL checks…"):
                try:
                    st.session_state[RESULT_KEY] = api_client.scan_message(
                        text=text,
                        scan_type=scan_type,
                        language=language,
                        include_explanation=include_explanation,
                    )
                except api_client.APIError as exc:
                    st.error(f"Analysis failed: {exc}")
                    st.session_state[RESULT_KEY] = None

    result = st.session_state.get(RESULT_KEY)
    if result:
        st.divider()
        result_view.render(result)

        col_a, col_b, col_c = st.columns([1, 1, 2])
        with col_a:
            if st.button("Analyse another", width="stretch"):
                st.session_state[RESULT_KEY] = None
                st.session_state[SAMPLE_KEY] = ""
                st.rerun()
        with col_b:
            st.download_button(
                "Download JSON",
                data=__import__("json").dumps(result, indent=2, ensure_ascii=False),
                file_name=f"scamshield_{result['scan_id'][:8]}.json",
                mime="application/json",
                width="stretch",
            )
        with col_c:
            st.caption("This scan is saved in History. You can delete it at any time.")
    else:
        ui.note(
            "Tip: try the 'KYC / bank phishing SMS' example, then switch the explanation "
            "language to Hinglish and analyse it again — the detection is identical, only "
            "the narrative changes."
        )
