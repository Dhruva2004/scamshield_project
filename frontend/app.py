"""
ScamShield AI - frontend/app.py
===============================
Streamlit entry point.

Run with:
    streamlit run frontend/app.py

Structure
---------
    frontend/
      app.py                 <- this file: page config, navigation, routing
      api_client.py          <- the only module that speaks HTTP
      components/
        ui.py                <- HTML/CSS building blocks
        charts.py            <- Altair builders
        result_view.py       <- renders one scan result
      views/
        dashboard.py
        analyser.py
        url_page.py
        history_page.py
        statistics_page.py
        about_page.py
      styles/theme.css

Why Streamlit (and why the architecture is React-ready)
-------------------------------------------------------
Streamlit gives a professional-looking data app in pure Python, which keeps the
project honest: the same developer can own backend, ML and UI. All data access is
isolated in `api_client.py`, which talks to a versioned REST API, so a future
React frontend would consume exactly the same endpoints without any backend
change.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Allow `import frontend.x` when Streamlit runs this file directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend import api_client  # noqa: E402
from frontend.components import ui  # noqa: E402
from frontend.views import (  # noqa: E402
    about_page,
    analyser,
    dashboard,
    history_page,
    statistics_page,
    url_page,
)

# ---------------------------------------------------------------------------
# Page configuration (must run before any other Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="ScamShield AI — Scam & Phishing Detection",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

ui.inject_theme()

PAGES = {
    "Dashboard": dashboard.render,
    "Message Analyser": analyser.render,
    "URL Analyser": url_page.render,
    "History": history_page.render,
    "Statistics": statistics_page.render,
    "About": about_page.render,
}


def _sidebar() -> str:
    """Sidebar branding, navigation and live status."""
    with st.sidebar:
        st.markdown(
            """
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
              <div class="ss-logo" style="width:38px;height:38px;font-size:20px;">🛡️</div>
              <div>
                <div style="font-weight:700;font-size:1.05rem;">ScamShield AI</div>
                <div style="color:#96a7c4;font-size:0.75rem;">Detect · Explain · Protect</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        page = st.radio("Navigation", list(PAGES.keys()), label_visibility="collapsed")

        st.divider()
        st.caption("SYSTEM STATUS")
        try:
            health = api_client.health()
            st.success("API online", icon="✅")
            model_ok = health.get("model_available")
            gemini_ok = health.get("gemini_configured")
            st.markdown(
                f"""
                <div style="font-size:0.78rem;color:#96a7c4;line-height:1.85;">
                  ML model: <b style="color:{'#22c55e' if model_ok else '#f59e0b'};">
                  {'ready' if model_ok else 'not trained'}</b><br>
                  Gemini: <b style="color:{'#22c55e' if gemini_ok else '#f59e0b'};">
                  {'configured' if gemini_ok else 'not configured'}</b><br>
                  Database: <b>{health.get('database_backend', 'sqlite')}</b><br>
                  Version: <b>{health.get('version', '—')}</b>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(f"API: {api_client.api_base_url()}")

            if api_client.secrets_error():
                st.error(
                    "Your Streamlit **secrets** block could not be parsed.\n\n"
                    "Open *Manage app -> Settings -> Secrets* and check the TOML "
                    "syntax - every line needs quotes around the value.",
                    icon="🔑",
                )

            if not gemini_ok:
                st.caption("Explanations use the built-in fallback until GEMINI_API_KEY is set.")
        except api_client.APIError:
            st.error("API offline", icon="⚠️")
            st.caption(
                "Start the backend:\n\n`uvicorn backend.main:app --port 8000`"
            )

        st.divider()
        st.caption(
            "Guidance only — never a guarantee. "
            "Report fraud at cybercrime.gov.in or call 1930 (India)."
        )
    return page


def main() -> None:
    page = _sidebar()

    ui.header(
        "ScamShield AI",
        "AI-powered detection of scam, spam and phishing messages · "
        "MSc Computer Science / Samsung Innovation Campus",
    )

    renderer = PAGES.get(page)
    if renderer is None:  # pragma: no cover - defensive
        st.error(f"Unknown page: {page}")
        return

    try:
        renderer()
    except api_client.APIError as exc:
        st.error(f"Backend error: {exc}")
        st.info(
            "Make sure the API is running:\n\n"
            "```\nuvicorn backend.main:app --reload --port 8000\n```"
        )
    except Exception as exc:  # pragma: no cover - last-resort guard
        st.error(f"Unexpected error on this page: {type(exc).__name__}: {exc}")
        st.caption("The rest of the app is unaffected. Check the backend logs for details.")


if __name__ == "__main__":
    main()
else:
    # Streamlit imports this module rather than running it as __main__.
    main()
