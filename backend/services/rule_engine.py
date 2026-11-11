"""
ScamShield AI - backend/services/rule_engine.py
===============================================
The explainable rule-based detector.

How the score is computed
-------------------------
1. Every rule in `rule_catalog.ALL_RULES` is tested against BOTH:
     * the canonicalised text (de-obfuscated: "K.Y.C" -> "kyc", "acc0unt" -> "account")
     * the raw lowercased text (so we still see the original "http://" spelling)
2. Each triggered rule contributes its severity weight:
       info 0 | low 6 | medium 12 | high 20 | critical 32
3. **Category de-duplication** (important for honest scoring):
   within one category only the highest-weight hit counts in full; further
   hits add at most 6 points each, and at most 2 extra hits per category.
   Without this, a single message containing "urgent ... immediately ... right
   now" would add 36 points for saying the same thing three times.
4. Context-only rules (a link, a bank name, an OTP mention) are capped: they
   can contribute at most 10 points in total, and only if at least one
   *substantive* rule also fired.
5. Several rule pairs form **combinations** that are far more dangerous than
   either alone (e.g. KYC + link = classic KYC phishing). These add a bonus.

The result is a 0-100 rule score, a risk level, and a list of findings that
the UI can display verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from backend.core.logging_config import get_logger
from backend.schemas.common import RiskLevel, Severity
from backend.schemas.scan import RuleEngineResult, RuleFinding
from backend.services import rule_catalog
from backend.services.rule_catalog import (
    ALL_RULES,
    CONTEXT_ONLY_RULE_IDS,
    RuleSpec,
)
from ml.preprocessing.normalize import canonicalize, normalize

logger = get_logger(__name__)

# Extra points granted per additional hit inside the same category.
_SECONDARY_HIT_POINTS = 6
_MAX_SECONDARY_HITS_PER_CATEGORY = 2
# Ceiling for context-only rules.
_CONTEXT_ONLY_CAP = 10
# Maximum length of a snippet echoed back to the user (prevents huge payloads).
_MATCH_SNIPPET_LEN = 80


@dataclass(frozen=True)
class RuleCombination:
    """
    Two rules that together mean much more than each alone.

    Example: "kyc" (HIGH, 20) + "link" (LOW, 6) is not a weak signal - it is
    the exact shape of the most common Indian bank phishing SMS.
    """

    combination_id: str
    rule_ids: Tuple[str, ...]
    weight: int
    title: str
    description: str
    severity: Severity


# ---------------------------------------------------------------------------
# Combinations (domain knowledge encoded as data)
# ---------------------------------------------------------------------------
COMBINATIONS: Sequence[RuleCombination] = (
    RuleCombination(
        combination_id="C_KYC_PHISHING",
        rule_ids=("R_KYC_SCAM", "R_LINK_PRESENT"),
        weight=18,
        title="KYC claim combined with a link",
        description=(
            "A KYC-expiry claim plus a link is the single most common bank phishing "
            "pattern in India. Real KYC reminders ask you to visit a branch or use the app."
        ),
        severity=Severity.CRITICAL,
    ),
    RuleCombination(
        combination_id="C_OTP_PLUS_LINK",
        rule_ids=("R_OTP_MENTIONED", "R_LINK_PRESENT"),
        weight=16,
        title="OTP mentioned together with a link",
        description=(
            "An OTP reference plus a link usually means the page will ask you to type the "
            "code that just arrived on your phone - handing over your account."
        ),
        severity=Severity.CRITICAL,
    ),
    RuleCombination(
        combination_id="C_URGENT_THREAT",
        rule_ids=("R_URGENCY_LANGUAGE", "R_THREAT_LANGUAGE"),
        weight=14,
        title="Urgency combined with a threat",
        description=(
            "Panic + deadline is the core pressure tactic: 'act in 24 hours or your "
            "account is blocked'."
        ),
        severity=Severity.HIGH,
    ),
    RuleCombination(
        combination_id="C_PAYMENT_THREAT",
        rule_ids=("R_UPI_PAYMENT_REQUEST", "R_THREAT_LANGUAGE"),
        weight=16,
        title="Payment request combined with a threat",
        description=(
            "Being pushed to pay while being threatened is a hallmark of extortion and "
            "'digital arrest' frauds."
        ),
        severity=Severity.CRITICAL,
    ),
    RuleCombination(
        combination_id="C_JOB_FEE",
        rule_ids=("R_FAKE_JOB_OFFER", "R_UPI_PAYMENT_REQUEST"),
        weight=14,
        title="Job offer that requires a payment",
        description=(
            "A genuine employer never asks a candidate for a registration, training or "
            "security deposit."
        ),
        severity=Severity.CRITICAL,
    ),
    RuleCombination(
        combination_id="C_PRIZE_FEE",
        rule_ids=("R_LOTTERY_PRIZE", "R_UPI_PAYMENT_REQUEST"),
        weight=14,
        title="Prize claim that requires a payment",
        description=(
            "'Pay the processing fee to release your prize' is advance-fee fraud - there "
            "is no prize."
        ),
        severity=Severity.CRITICAL,
    ),
    RuleCombination(
        combination_id="C_CREDENTIAL_LINK",
        rule_ids=("R_CREDENTIAL_LINK_COMBO", "R_NON_HTTPS_LINK"),
        weight=10,
        title="Credential request over a non-HTTPS link",
        description=(
            "Asking for logins on a plain-HTTP page means anything you type can be "
            "intercepted in transit."
        ),
        severity=Severity.CRITICAL,
    ),
    RuleCombination(
        combination_id="C_APK_AND_PAYMENT",
        rule_ids=("R_APK_OR_FILE_DOWNLOAD", "R_UPI_PAYMENT_REQUEST"),
        weight=12,
        title="App install plus a payment request",
        description=(
            "Installing a remote-access app and then 'paying' is how screen-sharing "
            "banking fraud drains accounts."
        ),
        severity=Severity.CRITICAL,
    ),
)

# Compile every pattern once at import time.
_COMPILED: Dict[str, List[re.Pattern]] = {
    rule.rule_id: [re.compile(pattern, re.IGNORECASE) for pattern in rule.patterns]
    for rule in ALL_RULES
}
_COMBINATION_INDEX = {c.combination_id: c for c in COMBINATIONS}


def _summarise_match(text: str, match: re.Match) -> str:
    """
    Return a short, readable snippet around a regex match.

    We keep the surrounding context because "share your OTP" is far more
    convincing to a user than the bare word "otp".
    """
    start = max(0, match.start() - 25)
    end = min(len(text), match.end() + 25)
    snippet = " ".join(text[start:end].split())
    if len(snippet) > _MATCH_SNIPPET_LEN:
        snippet = snippet[:_MATCH_SNIPPET_LEN] + "…"
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _find_hits(rule: RuleSpec, haystacks: Iterable[str]) -> List[str]:
    """
    Test one rule against the given text variants.

    Returns up to 3 distinct matched snippets (trimmed for the API payload).
    """
    matches: List[str] = []
    seen = set()
    compiled_patterns = _COMPILED.get(rule.rule_id, [])
    for text in haystacks:
        if not text:
            continue
        for pattern in compiled_patterns:
            for found in pattern.finditer(text):
                snippet = _summarise_match(text, found)
                key = snippet.lower()
                if key not in seen:
                    seen.add(key)
                    matches.append(snippet)
                if len(matches) >= 3:
                    return matches
    return matches


class RuleEngine:
    """
    Stateless rule-based detector.

    `analyse(text)` is pure: same input -> same output, no database, no network.
    That makes it trivially unit-testable and safe to run on every request.
    """

    def __init__(self, rules: Sequence[RuleSpec] = ALL_RULES) -> None:
        self.rules = list(rules)

    # ------------------------------------------------------------------
    def evaluate(self, text: str) -> List[RuleFinding]:
        """
        Return every triggered rule as a RuleFinding, sorted by severity.
        Kept public because the API exposes the raw findings to the UI.
        """
        if not text or not text.strip():
            return []

        normalized = normalize(text)
        canonical = canonicalize(text)
        # Both variants are searched: canonicalised text defeats obfuscation,
        # while the lowercase original preserves literal URLs like "http://".
        haystacks = [canonical, normalized.lower()]

        findings: List[RuleFinding] = []
        for rule in self.rules:
            matches = _find_hits(rule, haystacks)
            if len(matches) < max(1, rule.min_hits):
                continue
            findings.append(
                RuleFinding(
                    rule_id=rule.rule_id,
                    title=rule.title,
                    category=rule.category,
                    description=rule.description,
                    severity=rule.severity,
                    matched_text=matches,
                    weight=rule.severity.weight,
                )
            )

        # Highest severity first, then the heavier weight.
        findings.sort(key=lambda f: (-f.severity.weight, f.rule_id))
        return findings

    # ------------------------------------------------------------------
    def _score(self, findings: List[RuleFinding]) -> Tuple[int, List[str]]:
        """
        Convert findings into a 0-100 score.

        Returns (score, reasons) where `reasons` are short human sentences
        used by the risk assessor and the UI.
        """
        if not findings:
            return 0, []

        reasons: List[str] = []

        # Split substantive rules from context-only rules.
        substantive = [f for f in findings if f.rule_id not in CONTEXT_ONLY_RULE_IDS]
        context_only = [f for f in findings if f.rule_id in CONTEXT_ONLY_RULE_IDS]

        # ----- group substantive rules by category, keep the heaviest -----
        best_per_category: Dict[str, RuleFinding] = {}
        extras_per_category: Dict[str, List[RuleFinding]] = {}
        for finding in substantive:
            current = best_per_category.get(finding.category)
            if current is None or finding.weight > current.weight:
                if current is not None:
                    extras_per_category.setdefault(finding.category, []).append(current)
                best_per_category[finding.category] = finding
            else:
                extras_per_category.setdefault(finding.category, []).append(finding)

        score = 0
        for category, finding in best_per_category.items():
            score += finding.weight
            reasons.append(f"{finding.title} (+{finding.weight})")
            extras = extras_per_category.get(category, [])
            bonus_hits = extras[:_MAX_SECONDARY_HITS_PER_CATEGORY]
            if bonus_hits:
                bonus = _SECONDARY_HIT_POINTS * len(bonus_hits)
                score += bonus
                reasons.append(
                    f"{len(bonus_hits)} additional '{category}' indicator(s) (+{bonus})"
                )

        # ----- context-only contribution, capped and gated -----
        if context_only and substantive:
            caps = min(_CONTEXT_ONLY_CAP, sum(f.weight for f in context_only))
            score += caps
            reasons.append(
                "Supporting context: "
                + ", ".join(f.title.lower() for f in context_only)
                + f" (+{caps})"
            )
        elif context_only:
            # Nothing substantive fired: a link or a bank name alone is not a
            # verdict. Give at most 6 points so the UI can still say "low".
            caps = min(6, sum(f.weight for f in context_only))
            score += caps
            if caps:
                reasons.append("Only weak context indicators were found (+{})".format(caps))

        # ----- dangerous combinations -----
        triggered_ids = {f.rule_id for f in findings}
        for combo in COMBINATIONS:
            if all(rule_id in triggered_ids for rule_id in combo.rule_ids):
                score += combo.weight
                reasons.append(f"{combo.title} (+{combo.weight})")

        # ----- diversity bonus: many independent categories = worse -----
        independent_categories = len(best_per_category)
        if independent_categories >= 4:
            score += 8
            reasons.append("Indicators span 4+ independent categories (+8)")
        elif independent_categories == 3:
            score += 4
            reasons.append("Indicators span 3 independent categories (+4)")

        score = min(100, score)

        # --- severity floor -------------------------------------------
        # Some rules describe near-certain scam mechanics (sharing an OTP,
        # installing an APK, a secrecy demand). A message that triggers one of
        # them should never be reported as merely "medium" just because the
        # other categories stayed quiet. Documented policy:
        #     1 critical rule  -> at least 65 (HIGH)
        #     2+ critical rules-> at least 75 (CRITICAL)
        critical_ids = {
            f.rule_id for f in findings if f.severity is Severity.CRITICAL
        }
        if len(critical_ids) >= 2 and score < 75:
            reasons.append(
                f"Floor applied: {len(critical_ids)} critical-severity indicators (raised to 75)"
            )
            score = 75
        elif len(critical_ids) == 1 and score < 65:
            reasons.append("Floor applied: 1 critical-severity indicator (raised to 65)")
            score = 65

        # --- genuine-transaction-alert safeguard -----------------------
        # If the message structurally looks like an automated bank alert and
        # NOTHING of high/critical severity fired, cap the score. Rationale:
        # the remaining hits in such a message ("to VPA x@okhdfcbank" is the
        # recipient of YOUR payment, not a request to pay) are structural
        # artefacts, not scam evidence. A real scam that copies the format will
        # still trigger high/critical rules (link, KYC, OTP, threat), so this
        # cap cannot be exploited to smuggle a scam through.
        fired_ids = {f.rule_id for f in findings}
        looks_transactional = "R_TRANSACTIONAL_ALERT_STRUCTURE" in fired_ids
        severe_hits = [
            f for f in findings
            if f.severity in {Severity.HIGH, Severity.CRITICAL}
            and f.rule_id not in CONTEXT_ONLY_RULE_IDS
        ]
        if looks_transactional and not severe_hits and score > 15:
            reasons.append(
                "Score capped at 15: genuine-transaction format with no high-severity "
                "indicator (the account/UPI reference is the recipient of your own payment)"
            )
            score = 15

        return score, reasons

    # ------------------------------------------------------------------
    def score_to_level(self, score: int) -> RiskLevel:
        """Map a 0-100 rule score onto the user-facing risk buckets."""
        if score >= 70:
            return RiskLevel.CRITICAL
        if score >= 45:
            return RiskLevel.HIGH
        if score >= 20:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # ------------------------------------------------------------------
    def analyse(self, text: str) -> RuleEngineResult:
        """
        Public entry point used by the scan service and the API.

        Returns a RuleEngineResult with score, level, findings, categories and
        the human reasons behind the score.
        """
        findings = self.evaluate(text)
        score, reasons = self._score(findings)
        categories = sorted({f.category for f in findings})

        result = RuleEngineResult(
            score=score,
            risk_level=self.score_to_level(score),
            findings=findings,
            categories=categories,
            matched_count=len(findings),
        )
        # `reasons` is needed by the risk assessor; stash it without polluting
        # the public schema (Pydantic models are mutable by default).
        object.__setattr__(result, "_reasons", reasons)
        return result


# Singleton used by the API layer.
rule_engine = RuleEngine()


def get_rule_engine() -> RuleEngine:
    return rule_engine
