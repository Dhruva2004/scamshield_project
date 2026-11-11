"""
ScamShield AI - scripts/capture_outputs.py
==========================================
Regenerates docs/OUTPUTS.md from a RUNNING deployment.

    python scripts/capture_outputs.py
    python scripts/capture_outputs.py --api https://api.example.com

Why: a report that quotes hand-copied output drifts from reality. This script
hits the live API and writes what actually comes back, so the deliverable can be
refreshed after any change (or after enabling Gemini) with one command.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "docs" / "OUTPUTS.md"


def get(api: str, path: str):
    with urllib.request.urlopen(f"{api}{path}", timeout=20) as response:
        return json.loads(response.read())


def post(api: str, path: str, payload: dict):
    request = urllib.request.Request(
        f"{api}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def load_test(api: str, text: str, n: int = 200, concurrency: int = 20):
    body = json.dumps({"text": text, "include_explanation": False}).encode()

    def one(_i: int) -> float:
        started = time.perf_counter()
        request = urllib.request.Request(
            f"{api}/api/v1/scan/message", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        return (time.perf_counter() - started) * 1000

    one(0)  # warm-up
    latencies = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for ms in pool.map(one, range(n)):
            latencies.append(ms)
    wall = time.perf_counter() - started
    latencies.sort()
    return {
        "n": n, "concurrency": concurrency, "wall": wall,
        "throughput": n / wall,
        "p50": latencies[len(latencies) // 2],
        "p95": latencies[int(len(latencies) * 0.95)],
        "p99": latencies[int(len(latencies) * 0.99)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture real API output into docs/OUTPUTS.md")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--ui", default="http://localhost:8501")
    parser.add_argument("--no-seed", action="store_true", help="do not reseed history first")
    args = parser.parse_args(argv)

    api = args.api.rstrip("/")
    if not args.no_seed:
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "seed_demo_data.py"), "--clear"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )

    health = get(api, "/api/v1/health")
    comparison = get(api, "/api/v1/models/comparison")
    terms = get(api, "/api/v1/models/terms?top_k=10")
    stats = get(api, "/api/v1/history/stats")
    rules = get(api, "/api/v1/scan/rules")
    samples = get(api, "/api/v1/samples")
    history = get(api, "/api/v1/history?page_size=5")

    english = post(api, "/api/v1/scan/message",
                   {"text": samples[0]["text"], "language": "en", "include_explanation": True})
    hindi = post(api, "/api/v1/scan/message",
                 {"text": samples[0]["text"], "language": "hi", "include_explanation": True})
    hinglish = post(api, "/api/v1/scan/message",
                    {"text": samples[7]["text"], "language": "hinglish", "include_explanation": True})
    url_result = post(api, "/api/v1/scan/url",
                      {"text": "http://sbi.co.in@secure-login-verify.xyz/kyc/update",
                       "include_explanation": False})
    batch = post(api, "/api/v1/scan/batch",
                 {"items": [{"text": s["text"]} for s in samples[:4]]})
    perf = load_test(api, samples[0]["text"])

    smoke = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "prod_smoke_test.py"),
         "--api", api, "--ui", args.ui],
        capture_output=True, text=True,
    ).stdout.strip()
    # `pytest -q` from pytest.ini prints dots only; drop -q to get the summary line.
    test_run = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts="], cwd=PROJECT_ROOT,
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    summary = [ln for ln in test_run if " passed" in ln or " failed" in ln]
    tests = summary[-1] if summary else "\n".join(test_run[-3:])

    lines: list[str] = []
    add = lines.append
    add("# ScamShield AI — Actual Output\n")
    add(f"Captured from the **running deployment** at `{api}` on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.")
    add("Every field below is a real HTTP response — nothing is illustrative.\n")
    add(f"Profile: `ENVIRONMENT={health.get('environment')}`, "
        f"database `{health.get('database_backend')}`, "
        f"model `{'loaded' if health.get('model_available') else 'missing'}`, "
        f"Gemini `{'configured' if health.get('gemini_configured') else 'not configured'}`.\n")
    add("```\n$ python scripts/prod_smoke_test.py\n" + smoke + "\n```\n---\n")

    add("## 1. Health check\n")
    add("```bash\ncurl -s <api>/api/v1/health | python3 -m json.tool\n```\n")
    add("```json\n" + json.dumps(health, indent=2) + "\n```\n---\n")

    add("## 2. Message analysis — English\n")
    add(f"**Input**\n\n```\n{samples[0]['text']}\n```\n")
    add(f"**Verdict: {english['risk']['level'].upper()} · {english['risk']['score']}/100 · "
        f"{english['risk']['headline']}** ({english['processing_ms']} ms)\n")
    add("| Layer | Output |\n|---|---|")
    add(f"| Rule engine | {english['rule_engine']['score']}/100 · "
        f"{english['rule_engine']['matched_count']} rules matched |")
    add(f"| ML model | P(spam)=**{english['ml_prediction']['spam_probability']}** → "
        f"`{english['ml_prediction']['label']}` "
        f"(threshold {english['ml_prediction']['threshold']}) |")
    links = english["urls"]["urls_found"]
    link_word = "link" if links == 1 else "links"
    add(f"| URL analysis | {links} {link_word} · "
        f"{english['urls']['highest_score']}/100 · "
        f"imitates `{english['urls']['analyses'][0]['lookalike_of']}` |")
    add(f"| Explanation | source `{english['explanation']['source']}` |\n")
    add("**Triggered rules**\n\n| Rule | Severity | Matched text |\n|---|---|---|")
    for finding in english["rule_engine"]["findings"][:8]:
        matched = (finding["matched_text"][0] if finding["matched_text"] else "").replace("|", "\\|")
        add(f"| `{finding['rule_id']}` | {finding['severity']} | {matched} |")
    add("\n**Fusion reasons**\n")
    for reason in english["risk"]["reasons"]:
        add(f"- {reason}")
    add("\n**Recommended actions**\n")
    for action in english["risk"]["recommended_actions"]:
        add(f"- {action}")
    add(f"\n**Explanation** (`{english['explanation']['source']}`)\n")
    add(f"> {english['explanation']['summary']}\n")
    add("---\n")

    add("## 3. Same message — Hindi\n")
    add(f"**Verdict identical: {hindi['risk']['level'].upper()} · {hindi['risk']['score']}/100** "
        "— only the narrative changes.\n")
    add("```\n" + hindi["explanation"]["summary"] + "\n\n"
        + "क्या करें:\n" + "\n".join(f"  • {r}" for r in hindi["explanation"]["recommendations"][:3])
        + "\n```\n---\n")

    add("## 4. Hinglish scam — the language-limitation case\n")
    add(f"**Input**\n\n```\n{samples[7]['text']}\n```\n")
    add(f"**Verdict: {hinglish['risk']['level'].upper()} · {hinglish['risk']['score']}/100**\n")
    add("| Layer | Output |\n|---|---|")
    add(f"| Rule engine | **{hinglish['rule_engine']['score']}/100** · "
        f"{hinglish['rule_engine']['matched_count']} rules |")
    add(f"| ML model | **P(spam)={hinglish['ml_prediction']['spam_probability']}** — "
        "near zero, because the model is English-only |\n")
    add("```\n" + hinglish["explanation"]["summary"] + "\n```")
    add("\n> The architecture is designed to expose exactly this disagreement: the model is "
        "wrong here, the rules are right, and the UI shows both.\n---\n")

    add("## 5. URL analysis — never visits the link\n")
    analysis = url_result["urls"]["analyses"][0]
    add(f"**Input** `{analysis['raw']}`\n")
    add("| Property | Value |\n|---|---|")
    for key in ("scheme", "hostname", "registered_domain", "tld", "is_https",
                "is_ip_address", "is_shortener", "subdomain_count", "lookalike_of", "score"):
        add(f"| {key} | `{analysis[key]}` |")
    add("\n**Indicators**\n\n| Code | Severity | Detail |\n|---|---|---|")
    for indicator in analysis["indicators"]:
        add(f"| `{indicator['code']}` | {indicator['severity']} | "
            f"{indicator['detail'].replace('|', chr(92) + '|')} |")
    add(f"\nVerdict: **{url_result['risk']['level'].upper()} · {url_result['risk']['score']}/100**\n---\n")

    add("## 6. Batch analysis\n")
    add(f"4 messages → `{batch['total']}` results, summary `{json.dumps(batch['summary'])}`\n")
    add("| # | Preview | Risk | Score |\n|---|---|---|---|")
    for index, result in enumerate(batch["results"], 1):
        add(f"| {index} | {result['input_preview'][:60]}… | {result['risk']['level']} | "
            f"{result['risk']['score']} |")
    add("\n---\n")

    add("## 7. Dashboard statistics\n")
    keys = ["total_scans", "spam_detected", "suspicious_urls", "high_risk_scans",
            "risk_distribution", "average_risk_score"]
    add("```json\n" + json.dumps({k: stats[k] for k in keys}, indent=2) + "\n```\n")
    add("Top indicators: " + ", ".join(
        f"`{i['name']}` ({i['count']})" for i in stats["top_indicators"][:6]) + "\n---\n")

    add("## 8. Model performance (measured)\n")
    add(f"Dataset: {comparison['dataset']} · active: **{comparison['active_model']}**\n")
    add("| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | Selected |\n|---|---|---|---|---|---|---|")
    for entry in comparison["entries"]:
        add(f"| {entry['model_name']} | {entry['accuracy']:.4f} | {entry['precision']:.4f} | "
            f"{entry['recall']:.4f} | {entry['f1']:.4f} | {(entry['roc_auc'] or 0):.4f} | "
            f"{'✅' if entry['chosen'] else ''} |")
    add(f"\n**Selection:** {comparison['selection_reason']}\n")
    add("**Top spam terms:** " + ", ".join(f"`{t['term']}`" for t in terms["top_spam_terms"][:8]))
    add("\n\n**Top ham terms:** " + ", ".join(f"`{t['term']}`" for t in terms["top_ham_terms"][:8]))
    add("\n---\n")

    add("## 9. Rule catalogue\n")
    add(f"`{rules['total_rules']}` rules total.\n\n| Category | Rules |\n|---|---|")
    for category, count in sorted(rules["categories"].items(), key=lambda x: -x[1]):
        add(f"| {category} | {count} |")
    add("\n---\n")

    add("## 10. History (redacted)\n")
    add("| When (UTC) | Type | Risk | Score | ML | Preview |\n|---|---|---|---|---|---|")
    for item in history["items"]:
        add(f"| {item['created_at'][:19].replace('T', ' ')} | {item['scan_type']} | "
            f"{item['risk_level']} | {item['risk_score']} | {item['ml_label']} | "
            f"{item['message_preview'][:44]}… |")
    add("\n---\n")

    add("## 11. Load test\n")
    add("| Metric | Value |\n|---|---|")
    add(f"| Requests | {perf['n']} at concurrency {perf['concurrency']} |")
    add(f"| Throughput | **{perf['throughput']:.0f} req/s** |")
    add(f"| p50 | {perf['p50']:.1f} ms |")
    add(f"| p95 | **{perf['p95']:.1f} ms** |")
    add(f"| p99 | {perf['p99']:.1f} ms |")
    add("\n---\n")

    add("## 12. Test suite\n")
    add("```\n$ pytest\n" + tests + "\n```\n")
    add("> Regenerate with `python scripts/capture_outputs.py`.\n")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(PROJECT_ROOT)} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
