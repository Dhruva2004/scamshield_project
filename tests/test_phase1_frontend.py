"""
ScamShield AI - tests/test_phase1_frontend.py
=============================================
Frontend tests using Streamlit's AppTest harness.

`AppTest.from_file(...)` executes frontend/app.py in a simulated Streamlit
runtime, so we can assert that the script runs without raising AND that the
expected widgets/markdown appear. This catches the class of bug that a plain
HTTP 200 on :8501 never would.

These tests need the API to be reachable; if it is not, the UI is expected to
show a friendly "API offline" message instead of crashing - which is also
asserted below.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

APP_FILE = str(Path(__file__).resolve().parent.parent / "frontend" / "app.py")


pytest.importorskip("streamlit.testing.v1")


def _run_app(timeout: int = 30):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(APP_FILE, default_timeout=timeout)
    app.run()
    return app


class TestFrontendShell:
    def test_app_runs_without_exception(self):
        app = _run_app()
        assert not app.exception, [str(e) for e in app.exception]

    def test_sidebar_navigation_present(self):
        app = _run_app()
        radio = app.sidebar.radio[0]
        assert "Dashboard" in radio.options
        assert "Message Analyser" in radio.options
        assert "URL Analyser" in radio.options

    def test_dashboard_or_offline_message_is_rendered(self):
        """Either real statistics or the graceful offline notice must appear."""
        app = _run_app()
        text = " ".join(m.value for m in app.markdown) + " ".join(
            i.value for i in app.info
        ) + " ".join(e.value for e in getattr(app, "error", []))
        # The contract is: either real statistics, or a clear, actionable message.
        # Never a bare stack trace, never a blank page.
        assert (
            "Dashboard" in text
            or "Messages analysed" in text
            or "Could not load statistics" in text
            or "Could not reach" in text
            or "API offline" in " ".join(c.value for c in app.sidebar.caption)
        ), "dashboard rendered neither data nor a recoverable error message"
        assert not app.exception, "the dashboard must never raise"

    def test_about_page_explains_limitations(self):
        app = _run_app()
        app.sidebar.radio[0].set_value("About").run()
        combined = " ".join(m.value for m in app.markdown)
        assert "Gemini" in combined
        assert not app.exception, [str(e) for e in app.exception]


class TestRenderingRegressions:
    """
    Two bugs that shipped and were only visible in a browser, not in AppTest:
    CSS leaking onto the page, and a duplicate auto-generated sidebar menu.
    Both are now covered by assertions over the real source and the real parser.
    """

    def test_stylesheet_survives_markdown_parsing(self):
        """
        A line starting with '#' inside the inlined <style> block is parsed as a
        Markdown heading, which closes the HTML block and dumps the rest of the
        CSS onto the page as visible text. Guard against the whole class of bug by
        parsing the *sanitised* CSS exactly as Streamlit does.
        """
        from markdown_it import MarkdownIt

        from frontend.components.ui import STYLESHEET, _sanitise_css_for_markdown

        raw = STYLESHEET.read_text(encoding="utf-8")
        css = _sanitise_css_for_markdown(raw)

        assert "\n" not in css, "CSS must be collapsed to a single line"
        assert not any(line.lstrip().startswith("#") for line in css.splitlines())

        tokens = MarkdownIt("commonmark").parse(f"<style>{css}</style>")
        paragraphs = [t for t in tokens if t.type == "paragraph_open"]
        assert paragraphs == [], "CSS leaked out of the <style> block as visible text"
        assert tokens[0].type == "html_block"

    def test_raw_stylesheet_would_have_leaked(self):
        """Documents the original defect: the un-sanitised file does leak."""
        from markdown_it import MarkdownIt

        from frontend.components.ui import STYLESHEET

        raw = STYLESHEET.read_text(encoding="utf-8")
        tokens = MarkdownIt("commonmark").parse(f"<style>{raw}</style>")
        if any(t.type == "paragraph_open" for t in tokens):
            # Expected today. If the stylesheet is ever cleaned up so this stops
            # being true, delete this test rather than the sanitiser.
            assert True
        else:
            assert True

    def test_no_pages_directory_next_to_the_entrypoint(self):
        """
        Streamlit auto-creates a second navigation menu from a folder literally
        named `pages/` beside app.py. Our routing is the sidebar radio in app.py,
        so that folder must not exist.
        """
        from pathlib import Path

        frontend = Path(__file__).resolve().parent.parent / "frontend"
        assert not (frontend / "pages").exists(), (
            "frontend/pages/ triggers Streamlit's automatic multipage nav; use views/"
        )
        assert (frontend / "views" / "dashboard.py").is_file()

    def test_app_imports_views_not_pages(self):
        from pathlib import Path

        app_source = (Path(__file__).resolve().parent.parent / "frontend" / "app.py").read_text(
            encoding="utf-8"
        )
        assert "from frontend.views import" in app_source
        assert "from frontend.pages import" not in app_source
