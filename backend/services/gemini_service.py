"""
ScamShield AI - backend/services/gemini_service.py
==================================================
The Generative-AI explanation layer (Google Gemini).

Critical design principle
--------------------------
Gemini is an EXPLAINER, never a DETECTOR.

The verdict comes from the rule engine and the ML model, which are
deterministic, testable and auditable. Gemini's only job is to take that
verdict and turn it into friendly language a non-technical user understands,
in the language they chose.

Consequences of that principle, visible in this file:
  * Gemini is given the findings; it is explicitly told not to invent new ones.
  * It is told never to state certainty about the sender's intent.
  * The raw message is redacted before it leaves our server.
  * Every failure path returns a useful deterministic fallback, so a missing
    key, an outage or a rate limit never breaks a scan.

Supported languages
-------------------
    en       English
    hi       Hindi (Devanagari)
    hinglish Hinglish (Hindi written in Latin script)

API surface
-----------
    explain(verdict_context, language, user_message) -> Explanation
    GeminiExplainer.available -> bool

The new `google-genai` SDK is preferred; if only the older
`google-generativeai` package is installed we fall back to it. If neither is
importable (or no key is set), we go straight to the deterministic fallback.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.config import get_settings
from backend.core.logging_config import get_logger
from backend.schemas.common import Language
from backend.schemas.scan import Explanation
from backend.services.privacy import redact

logger = get_logger(__name__)

# Hard cap: keeps prompts (and cost) bounded and stops pathological input.
MAX_PROMPT_MESSAGE_CHARS = 1500

LANGUAGE_NAMES = {
    Language.ENGLISH: "English",
    Language.HINDI: "Hindi (Devanagari script)",
    Language.HINGLISH: "Hinglish (Hindi written in Roman/Latin script, mixed with English)",
}

SYSTEM_INSTRUCTION = """You are ScamShield AI's explanation assistant, helping everyday \
users in India understand whether a message looks like a scam.

You will receive a JSON object with:
  * verdict          - the risk level and score decided by ScamShield's own engines
  * rule_findings    - the exact rules that fired, with the text they matched
  * ml_prediction    - a statistical spam probability
  * message          - the user's message with personal data already redacted

Your job is to explain the EXISTING verdict to the user. Non-negotiable rules:

1. Do NOT invent findings. Only reference indicators present in rule_findings.
2. Do NOT claim certainty about the sender's identity or intent. Say "this looks
   like", "a common sign of", "consistent with". Never "this is definitely a scam".
3. Do NOT state that the message is safe. Absence of indicators is not proof.
4. Structure the answer as compact JSON with exactly these keys:
     summary              (2-3 sentences, plain language)
     suspicious_elements  (array of short strings, one per flagged element)
     scam_techniques      (array of short strings, e.g. "urgency pressure")
     recommendations      (array of 3-5 concrete actions the user should take)
5. Write ALL text values in the requested language.
6. Never ask for or repeat OTPs, PINs, passwords or full card numbers.
7. Be warm, brief and practical - the reader may be frightened or in a hurry.
8. Return JSON only. No markdown fences, no commentary outside the JSON object.
"""


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------
TECHNIQUE_HINTS = {
    "otp": "OTP/credential theft",
    "credential": "credential theft",
    "phishing": "phishing via a fake login page",
    "urgency": "artificial urgency to stop you thinking",
    "threat": "fear and threats of loss",
    "impersonation": "impersonation of a trusted brand or authority",
    "kyc": "fake KYC-compliance pressure",
    "banking": "fake bank security alert",
    "payment": "irreversible payment request",
    "reward": "free-prize bait",
    "job": "fake job / task-scam offer",
    "investment": "get-rich-quick investment fraud",
    "link": "suspicious link delivery",
    "malware": "malicious app install",
    "social_engineering": "social engineering pressure",
    "obfuscation": "deliberate obfuscation to evade filters",
    "language": "locally-targeted scam wording",
    "contact": "fake helpline callback",
}

_FALLBACK_TEXT = {
    Language.ENGLISH: {
        "summary_risk": (
            "ScamShield's automated checks flagged this message as {level} risk "
            "(score {score}/100). {count} specific warning indicator(s) were found."
        ),
        "summary_safe": (
            "ScamShield's automated checks found no strong scam indicators in this "
            "message (score {score}/100). This is not a guarantee of safety - if the "
            "sender asks for money, OTPs or personal details, treat it with suspicion."
        ),
        "elements": "Detected",
        "recommend": [
            "Do not click any link in this message. Open the official app instead.",
            "Never share OTPs, PINs, passwords or card details with anyone.",
            "Verify the claim using the official phone number printed on your card or website.",
            "If money was already sent, report it to your bank immediately and file a complaint at cybercrime.gov.in.",
            "Report the message as spam and block the sender.",
        ],
        "disclaimer": (
            "Automated explanation (Gemini unavailable). This is guidance, not proof."
        ),
    },
    Language.HINDI: {
        "summary_risk": (
            "ScamShield के स्वचालित जाँच में यह संदेश {level} जोखिम वाला पाया गया "
            "(स्कोर {score}/100)। {count} चेतावनी संकेत मिले हैं।"
        ),
        "summary_safe": (
            "ScamShield की जाँच में इस संदेश में कोई स्पष्ट धोखाधड़ी संकेत नहीं मिला "
            "(स्कोर {score}/100)। यह सुरक्षा की गारंटी नहीं है - अगर किसी ने पैसे, OTP "
            "या निजी जानकारी मांगी है तो सतर्क रहें।"
        ),
        "elements": "पाए गए संकेत",
        "recommend": [
            "संदेश में दिए किसी भी लिंक पर क्लिक न करें। बैंक का आधिकारिक ऐप खोलें।",
            "OTP, PIN, पासवर्ड या कार्ड की जानकारी किसी के साथ साझा न करें।",
            "दावे की पुष्टि कार्ड या आधिकारिक वेबसाइट पर दिए नंबर से करें।",
            "पैसे भेज दिए हों तो तुरंत बैंक को सूचित करें और cybercrime.gov.in पर शिकायत करें।",
            "संदेश को स्पैम रिपोर्ट करें और भेजने वाले को ब्लॉक करें।",
        ],
        "disclaimer": "स्वचालित व्याख्या (Gemini उपलब्ध नहीं)। यह मार्गदर्शन है, प्रमाण नहीं।",
    },
    Language.HINGLISH: {
        "summary_risk": (
            "ScamShield ki automated jaanch me ye message {level} risk nikla hai "
            "(score {score}/100). {count} warning signs mile hain."
        ),
        "summary_safe": (
            "ScamShield ko is message me koi strong scam sign nahi mila (score {score}/100). "
            "Ye safety ki guarantee nahi hai - agar koi paise, OTP ya personal details "
            "maang raha hai to savdhaan rahein."
        ),
        "elements": "Mile hue signs",
        "recommend": [
            "Message me diye kisi bhi link par click na karein. Bank ka official app kholein.",
            "OTP, PIN, password ya card details kisi ke saath share na karein.",
            "Claim ko card ya official website ke number par call karke verify karein.",
            "Agar paise bhej diye hain to turant bank ko batayein aur cybercrime.gov.in par complaint karein.",
            "Message ko spam report karein aur sender ko block karein.",
        ],
        "disclaimer": "Automated explanation (Gemini unavailable). Ye guidance hai, proof nahi.",
    },
}


def build_fallback_explanation(
    language: Language,
    risk_level: str,
    risk_score: int,
    findings: List[Dict[str, Any]],
    error: Optional[str] = None,
) -> Explanation:
    """
    Deterministic explanation, always available.

    This is also what the user sees when Gemini is switched off, rate-limited
    or misconfigured - the product never goes blank just because a third-party
    API did.
    """
    strings = _FALLBACK_TEXT[language]
    is_risky = risk_score >= 20

    summary = (strings["summary_risk"] if is_risky else strings["summary_safe"]).format(
        level=risk_level, score=risk_score, count=len(findings)
    )

    elements = [f'{f["title"]}' for f in findings[:6]]
    techniques: List[str] = []
    seen = set()
    for finding in findings:
        hint = TECHNIQUE_HINTS.get(finding.get("category", ""), "")
        if hint and hint not in seen:
            seen.add(hint)
            techniques.append(hint)

    return Explanation(
        available=True,
        source="fallback",
        language=language,
        summary=summary,
        suspicious_elements=elements,
        scam_techniques=techniques[:5],
        recommendations=list(strings["recommend"]),
        disclaimer=strings["disclaimer"],
        error=error,
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
def build_prompt(
    verdict: Dict[str, Any], findings: List[Dict[str, Any]], language: Language, message: str
) -> str:
    """
    Build the user turn.

    The message is REDACTED first: phone numbers, emails, card numbers and OTP
    values are replaced with placeholders before anything leaves our server.
    That is a deliberate privacy decision - the explanation does not need your
    actual account number to be useful.
    """
    safe_message = redact(message or "")[:MAX_PROMPT_MESSAGE_CHARS]
    payload = {
        "verdict": verdict,
        "rule_findings": [
            {
                "title": finding.get("title"),
                "category": finding.get("category"),
                "severity": finding.get("severity"),
                "matched_text": (finding.get("matched_text") or [])[:2],
            }
            for finding in findings[:12]
        ],
        "message": safe_message,
        "requested_language": LANGUAGE_NAMES[language],
    }
    return (
        f"Explain the verdict below to the user in {LANGUAGE_NAMES[language]}.\n"
        "Return the JSON object described in your instructions.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse JSON out of an LLM response.

    Even with `response_mime_type="application/json"` a model occasionally
    wraps the payload in ```json fences. We therefore:
      1. strip markdown fences,
      2. try a direct parse,
      3. fall back to locating the outermost {...} block.
    """
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _as_string_list(value: Any, limit: int = 6) -> List[str]:
    """Coerce whatever the model returned into a list of short strings."""
    if isinstance(value, str):
        return [value.strip()][:limit]
    if isinstance(value, list):
        items = []
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                items.append(entry.strip())
            elif isinstance(entry, dict):
                text = entry.get("text") or entry.get("title") or entry.get("description")
                if text:
                    items.append(str(text).strip())
        return items[:limit]
    return []


# ---------------------------------------------------------------------------
# The explainer
# ---------------------------------------------------------------------------
@dataclass
class GeminiExplainer:
    """Thin, defensive wrapper around the Gemini SDK."""

    api_key: str = ""
    model_name: str = "gemini-2.0-flash"
    timeout_seconds: int = 25
    enabled: bool = True
    _client: Any = field(default=None, repr=False)
    _sdk: str = field(default="", repr=False)

    @classmethod
    def from_settings(cls) -> "GeminiExplainer":
        settings = get_settings()
        return cls(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
            enabled=settings.gemini_enabled,
        )

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """True only when enabled, configured and an SDK is importable."""
        if not self.enabled or not self.api_key.strip():
            return False
        return self._ensure_client() is not None

    # ------------------------------------------------------------------
    def _ensure_client(self) -> Any:
        """
        Lazily create the SDK client (so importing the app never needs a key).

        Tries the modern `google-genai` SDK first, then the legacy
        `google-generativeai` package, and remembers which one worked.
        """
        if self._client is not None:
            return self._client

        # --- modern SDK: from google import genai -----------------------
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore

            self._client = genai.Client(api_key=self.api_key)
            self._sdk = "google-genai"
            self._types = types
            logger.info("Gemini client ready (google-genai, model=%s)", self.model_name)
            return self._client
        except Exception as exc:  # ImportError or SDK error
            logger.debug("google-genai unavailable: %s", exc)

        # --- legacy SDK: import google.generativeai --------------------
        try:
            import google.generativeai as legacy  # type: ignore

            legacy.configure(api_key=self.api_key)
            self._client = legacy.GenerativeModel(self.model_name)
            self._sdk = "google-generativeai"
            logger.info("Gemini client ready (legacy SDK, model=%s)", self.model_name)
            return self._client
        except Exception as exc:
            logger.warning("No usable Gemini SDK installed: %s", exc)
            self._client = None
            return None

    # ------------------------------------------------------------------
    def _call_model(self, prompt: str) -> str:
        """Dispatch one generation call to whichever SDK is active."""
        if self._sdk == "google-genai":
            types = self._types
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3,          # low: we want consistent, factual tone
                    max_output_tokens=900,
                    response_mime_type="application/json",
                ),
            )
            return getattr(response, "text", "") or ""

        # Legacy SDK path
        model = self._client
        response = model.generate_content(
            f"{SYSTEM_INSTRUCTION}\n\n{prompt}",
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 900,
                "response_mime_type": "application/json",
            },
        )
        return getattr(response, "text", "") or ""

    # ------------------------------------------------------------------
    def explain(
        self,
        *,
        risk_level: str,
        risk_score: int,
        findings: List[Dict[str, Any]],
        message: str,
        language: Language,
    ) -> Explanation:
        """
        Produce an Explanation. ALWAYS returns a usable object.

        Failure ladder:
            no key / disabled  -> deterministic fallback (error noted)
            SDK error          -> fallback (error noted)
            unparsable JSON    -> fallback (error noted)
            valid JSON         -> Explanation(source="gemini")
        """
        if not self.enabled:
            return build_fallback_explanation(
                language, risk_level, risk_score, findings, error="Gemini disabled by configuration."
            )
        if not self.api_key.strip():
            return build_fallback_explanation(
                language, risk_level, risk_score, findings,
                error="GEMINI_API_KEY is not set.",
            )
        client = self._ensure_client()
        if client is None:
            return build_fallback_explanation(
                language, risk_level, risk_score, findings,
                error="No Gemini SDK available (pip install google-genai).",
            )

        verdict = {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "indicators_found": len(findings),
        }
        prompt = build_prompt(verdict, findings, language, message)

        try:
            raw = self._call_model(prompt)
        except Exception as exc:
            # Network error, quota, invalid key, safety block - all land here.
            logger.warning("Gemini call failed: %s: %s", type(exc).__name__, exc)
            return build_fallback_explanation(
                language, risk_level, risk_score, findings,
                error=f"Gemini request failed ({type(exc).__name__}).",
            )

        parsed = _extract_json(raw)
        if parsed is None:
            logger.warning("Gemini returned unparsable output (first 160 chars): %s", raw[:160])
            return build_fallback_explanation(
                language, risk_level, risk_score, findings,
                error="Gemini returned an unexpected format.",
            )

        summary = str(parsed.get("summary", "")).strip()
        recommendations = _as_string_list(parsed.get("recommendations"), limit=6)
        if not summary or not recommendations:
            return build_fallback_explanation(
                language, risk_level, risk_score, findings,
                error="Gemini response was missing required fields.",
            )

        return Explanation(
            available=True,
            source="gemini",
            language=language,
            summary=summary,
            suspicious_elements=_as_string_list(parsed.get("suspicious_elements"), limit=8),
            scam_techniques=_as_string_list(parsed.get("scam_techniques"), limit=6),
            recommendations=recommendations,
            disclaimer=(
                "AI-generated explanation. ScamShield gives guidance, not proof. "
                "Never share OTPs, PINs or passwords."
            ),
        )


_explainer: Optional[GeminiExplainer] = None


def get_explainer() -> GeminiExplainer:
    """Singleton explainer built from current settings."""
    global _explainer
    if _explainer is None:
        _explainer = GeminiExplainer.from_settings()
    return _explainer


def reset_explainer() -> None:
    """Test helper: rebuild after changing settings or mocking."""
    global _explainer
    _explainer = None
