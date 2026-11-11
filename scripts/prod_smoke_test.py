"""
ScamShield AI - scripts/prod_smoke_test.py
==========================================
Post-deployment smoke test.

Run this immediately after any deployment (container, VM, PaaS) to prove the
running service is actually healthy - not merely that the port is open.

    python scripts/prod_smoke_test.py
    python scripts/prod_smoke_test.py --api https://api.example.com --ui https://app.example.com

Exit code 0 = all checks passed, 1 = at least one failed (CI-friendly).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Tuple

import urllib.error
import urllib.request

TIMEOUT = 15
PASS, FAIL = "PASS", "FAIL"


def _get(url: str) -> Tuple[bool, Any, float, str]:
    """Return (ok, json_or_text, elapsed_ms, error)."""
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
            elapsed = (time.perf_counter() - started) * 1000
            try:
                return True, json.loads(raw), elapsed, ""
            except json.JSONDecodeError:
                return True, raw, elapsed, ""
    except urllib.error.HTTPError as exc:
        return False, None, 0.0, f"HTTP {exc.code}"
    except Exception as exc:  # URLError, timeout, DNS...
        return False, None, 0.0, f"{type(exc).__name__}: {exc}"


def _post(url: str, payload: Dict[str, Any]) -> Tuple[bool, Any, float, str]:
    started = time.perf_counter()
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            elapsed = (time.perf_counter() - started) * 1000
            return True, json.loads(response.read().decode()), elapsed, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        return False, None, 0.0, f"HTTP {exc.code}: {body}"
    except Exception as exc:
        return False, None, 0.0, f"{type(exc).__name__}: {exc}"


class Results:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.rows.append((PASS if ok else FAIL, name, detail))

    @property
    def failed(self) -> int:
        return sum(1 for status, _, _ in self.rows if status == FAIL)

    def render(self) -> None:
        width = max(len(name) for _, name, _ in self.rows) + 2
        print("\n" + "=" * (width + 46))
        for status, name, detail in self.rows:
            mark = "✓" if status == PASS else "✗"
            print(f" {mark} {name:<{width}} {detail}")
        print("=" * (width + 46))
        total = len(self.rows)
        print(f" {total - self.failed}/{total} checks passed")
        print("=" * (width + 46) + "\n")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ScamShield AI deployment smoke test")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--ui", default="http://localhost:8501", help="UI base URL")
    parser.add_argument("--api-key", default="", help="X-API-Key if enabled")
    args = parser.parse_args(argv)

    api = args.api.rstrip("/")
    ui = args.ui.rstrip("/")
    results = Results()

    # 1. API health
    ok, body, ms, err = _get(f"{api}/api/v1/health")
    results.add("API health", ok, f"{ms:.0f} ms" if ok else err)
    if ok and isinstance(body, dict):
        results.add("  status", body.get("status") == "ok", str(body.get("status")))
        components = body.get("components", {})
        results.add("  database", components.get("database") == "ok", components.get("database", "?"))
        results.add("  ml_model", components.get("ml_model") == "ok", components.get("ml_model", "?"))
        results.add("  gemini", True, components.get("gemini", "?") + " (optional)")

    # 2. Model artefacts — report the ACTIVE model, not whichever entry is first.
    ok, body, ms, err = _get(f"{api}/api/v1/models/comparison")
    if ok and isinstance(body, dict) and body.get("available"):
        entries = body.get("entries", [])
        chosen = next((e for e in entries if e.get("chosen")), entries[0] if entries else {})
        results.add(
            "Model metrics",
            bool(chosen),
            f"{chosen.get('model_name','?')} F1 {chosen.get('f1','?')} "
            f"({len(entries)} algorithms compared)",
        )
    else:
        results.add("Model metrics", False, err)

    # 3. Real scan: a known scam must be CRITICAL
    ok, body, ms, err = _post(
        f"{api}/api/v1/scan/message",
        {
            "text": "Dear Customer, your SBI KYC is suspended. Update at "
                    "http://sbi-kyc-verify.xyz/login within 24 hours.",
            "language": "en",
            "include_explanation": False,
        },
    )
    if ok and isinstance(body, dict):
        level = body.get("risk", {}).get("level")
        results.add("Scan scam sample", level == "critical", f"{level} in {ms:.0f} ms")
        results.add("  ML active", body.get("ml_prediction", {}).get("available") is True,
                    str(body.get("ml_prediction", {}).get("label")))
        results.add("  URL flagged", body.get("urls", {}).get("highest_score", 0) >= 40,
                    f"score {body.get('urls', {}).get('highest_score')}")
    else:
        results.add("Scan scam sample", False, err)

    # 4. Control case must not be critical
    ok, body, ms, err = _post(
        f"{api}/api/v1/scan/message",
        {"text": "Hi Rahul, are we still meeting at 6 pm?", "include_explanation": False},
    )
    if ok and isinstance(body, dict):
        level = body.get("risk", {}).get("level")
        results.add("Scan benign control", level == "low", level)
    else:
        results.add("Scan benign control", False, err)

    # 5. History + stats
    ok, body, ms, err = _get(f"{api}/api/v1/history/stats")
    results.add("Stats endpoint", ok and isinstance(body, dict) and "total_scans" in body,
                f"{body.get('total_scans')} scans" if ok else err)

    # 6. UI reachable
    ok, body, ms, err = _get(f"{ui}/_stcore/health")
    results.add("UI health", ok, f"{ms:.0f} ms" if ok else err)

    results.render()
    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
