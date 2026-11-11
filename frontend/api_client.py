"""
ScamShield AI - frontend/api_client.py
======================================
The ONLY module in the frontend that talks HTTP to the backend.

Why isolate it?
---------------
Every page imports `api_client`. If the API moves, the auth header changes or
we migrate to React later, only this file changes. It also centralises:
  * timeouts (a hung request must never freeze the UI),
  * error translation into a small typed exception,
  * retry-free, explicit behaviour (we show the user what happened).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

DEFAULT_TIMEOUT = 30
HEALTH_TIMEOUT = 5


class APIError(RuntimeError):
    """Raised for any non-2xx response or transport failure."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


DEFAULT_BASE_URL = "http://localhost:8000"


def _secret(key: str) -> str:
    """
    Read one setting from Streamlit secrets, then the environment, then "".

    Streamlit Community Cloud has no environment variables - everything is in the
    Secrets panel as TOML - so secrets must be consulted for *every* setting, not
    just the URL. A malformed secrets block is reported once, loudly, instead of
    being silently ignored: a silent fallback to localhost on a cloud host is one
    of the most confusing failures this app can produce.
    """
    try:
        import streamlit as st

        try:
            if key in st.secrets:  # type: ignore[attr-defined]
                return str(st.secrets[key]).strip()  # type: ignore[attr-defined]
        except Exception as exc:                      # malformed TOML
            st.session_state.setdefault("_ss_secrets_error", str(exc))
    except Exception:
        pass                                          # not running under Streamlit
    return os.getenv(key, "").strip()


def secrets_error() -> Optional[str]:
    """Return the secrets-parsing error, if one was recorded, else None."""
    try:
        import streamlit as st

        return st.session_state.get("_ss_secrets_error")
    except Exception:
        return None


def api_base_url() -> str:
    """The API root the UI is actually using. Shown in the sidebar for debugging."""
    configured = _secret("API_BASE_URL")
    return (configured or DEFAULT_BASE_URL).rstrip("/")


def _base_url() -> str:
    """
    Resolve the API root.

    Priority:
      1. Streamlit secrets  (Streamlit Community Cloud: Settings -> Secrets)
      2. API_BASE_URL environment variable (local shell / Docker)
      3. Localhost default
    """
    return api_base_url()


def _explain_http_error(status: int, url: str, detail: str, served_html: bool) -> str:
    """
    Turn an HTTP error into something that names the actual mistake.

    The URL is always included: without it, "404 Not Found" is unguessable, because
    the same status means different things at different paths.

    The HTML detection matters. Our API is FastAPI, which answers an unknown path
    with JSON: {"detail": "Not Found"}. An HTML 404 means the request never reached
    this application at all - a different service or a hosting platform's own
    not-found page answered instead.
    """
    lines = [f"{status} from {url}"]

    if served_html and status == 404:
        lines += [
            "",
            "You reached a web server, but not the ScamShield API - the response is an",
            "HTML page, while this API always answers with JSON.",
            "",
            "Most likely causes:",
            "  1. API_BASE_URL points at something else (another app, a placeholder",
            "     domain, or a hosting landing page). Open the API root in a browser:",
            "     it must show a small JSON document, not a website.",
            "  2. API_BASE_URL has a path suffix. Set the bare origin only:",
            '     https://your-api.onrender.com        (no /api/v1, no trailing slash)',
            "  3. The API service is not deployed yet, so the platform answered instead.",
        ]
    elif status == 401:
        lines += [
            "",
            "The API is reachable but rejected the request. Check that the API_KEY in",
            "Streamlit secrets is identical to the API_KEY set on the API host.",
        ]
    elif status == 403:
        lines += [
            "",
            "The API refused the request. A missing or wrong API_KEY usually causes 401;",
            "403 often means the key is valid but not allowed from this origin (CORS).",
        ]
    elif status == 422:
        lines += ["", "The API rejected the payload - this is a validation error, not a network problem."]
    elif status == 405:
        lines += ["", "Wrong HTTP method for this path - usually a mistake in the route, not the config."]
    elif status >= 500:
        lines += [
            "",
            "The API is reachable but failed internally. Check the API host's logs;",
            "the health endpoint may still work while a specific route is failing.",
        ]

    if detail:
        lines += ["", "Response:", detail]
    return "\n".join(lines)


def _headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    # Secrets first: on Streamlit Cloud there is no environment to read.
    api_key = _secret("API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _request(method: str, path: str, *, timeout: int = DEFAULT_TIMEOUT, **kwargs) -> Any:
    """Perform one HTTP request and normalise every failure into APIError."""
    url = f"{_base_url()}{path}"
    # Ensure JSON bodies are serialised once, consistently.
    if "json_body" in kwargs:
        kwargs["data"] = json.dumps(kwargs.pop("json_body"))
    try:
        response = requests.request(method, url, headers=_headers(), timeout=timeout, **kwargs)
    except requests.exceptions.ConnectionError as exc:
        base = _base_url()
        if "localhost" in base or "127.0.0.1" in base:
            # By far the most common cause: deployed to the cloud but the
            # API_BASE_URL secret was never set, so it fell back to localhost -
            # which on a hosting platform means the Streamlit container itself.
            hint = (
                f"Cannot reach the ScamShield API at {base}.\n\n"
                "If you are running this on Streamlit Community Cloud, open "
                "Manage app -> Settings -> Secrets and add:\n\n"
                '    API_BASE_URL = "https://your-api.onrender.com"\n'
                '    API_KEY = "the same value set on the API"\n\n'
                "On your own machine, start the backend first: "
                "uvicorn backend.main:app --port 8000"
            )
        else:
            hint = (
                f"Cannot reach the ScamShield API at {base}.\n\n"
                "Check that the service is running and publicly reachable. On a "
                "free Render instance it sleeps after 15 minutes idle and takes "
                "about 50 seconds to wake - reload the page. If it stays down, "
                "open /api/v1/health in a browser directly."
            )
        raise APIError(hint) from exc
    except requests.exceptions.Timeout as exc:
        raise APIError("The API request timed out. Please try again.") from exc

    if response.status_code >= 400:
        detail = ""
        served_html = False
        try:
            body = response.json()
            detail = body.get("message") or body.get("detail") or json.dumps(body)
        except ValueError:
            served_html = True
            detail = response.text[:300]
        raise APIError(
            _explain_http_error(response.status_code, url, detail, served_html),
            response.status_code,
            detail,
        )

    try:
        return response.json()
    except ValueError:
        return response.text


# ---------------------------------------------------------------------------
# Typed endpoint wrappers
# ---------------------------------------------------------------------------
def health() -> Dict[str, Any]:
    return _request("GET", "/api/v1/health", timeout=HEALTH_TIMEOUT)


def scan_message(
    text: str,
    scan_type: str = "auto",
    language: str = "en",
    include_explanation: bool = True,
) -> Dict[str, Any]:
    return _request(
        "POST",
        "/api/v1/scan/message",
        json_body={
            "text": text,
            "scan_type": scan_type,
            "language": language,
            "include_explanation": include_explanation,
        },
    )


def scan_url(
    url: str,
    language: str = "en",
    include_explanation: bool = True,
) -> Dict[str, Any]:
    return _request(
        "POST",
        "/api/v1/scan/url",
        json_body={
            "text": url,
            "scan_type": "url",
            "language": language,
            "include_explanation": include_explanation,
        },
    )


def scan_batch(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _request("POST", "/api/v1/scan/batch", json_body={"items": items})


def get_history(
    page: int = 1,
    page_size: int = 20,
    risk_level: Optional[str] = None,
    scan_type: Optional[str] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    params = {"page": page, "page_size": page_size}
    if risk_level:
        params["risk_level"] = risk_level
    if scan_type:
        params["scan_type"] = scan_type
    if search:
        params["search"] = search
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return _request("GET", f"/api/v1/history?{query}")


def get_history_item(scan_id: str) -> Dict[str, Any]:
    return _request("GET", f"/api/v1/history/{scan_id}")


def clear_history() -> Dict[str, Any]:
    return _request("DELETE", "/api/v1/history")


def delete_history_item(scan_id: str) -> Dict[str, Any]:
    return _request("DELETE", f"/api/v1/history/{scan_id}")


def get_stats() -> Dict[str, Any]:
    return _request("GET", "/api/v1/history/stats")


def get_model_comparison() -> Dict[str, Any]:
    return _request("GET", "/api/v1/models/comparison")


def export_history_csv() -> str:
    """Return the CSV export as text (used by the download button)."""
    return _request("GET", "/api/v1/history/export.csv")


def get_model_terms(top_k: int = 20) -> Dict[str, Any]:
    """Top spam/ham terms learned by the linear model."""
    return _request("GET", f"/api/v1/models/terms?top_k={top_k}")


def get_samples() -> List[Dict[str, Any]]:
    """Curated example messages used by the 'try an example' buttons."""
    return _request("GET", "/api/v1/samples")
