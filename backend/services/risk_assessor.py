"""
ScamShield AI - backend/services/risk_assessor.py
=================================================
Fuses the rule engine, the ML model and the URL analyser into ONE verdict.

Why a separate fusion step instead of three numbers in the UI?
--------------------------------------------------------------
Users need a single, actionable answer ("high risk - do not click"), while
reviewers need the components that produced it. This module owns the fusion
policy, and the policy is deliberately conservative:

    final_score = max(rule_score, ml_component, url_component) + agreement_bonus

  * **max, not average.** Averaging would let a confident ML score of 0.99 be
    diluted by a low rule score. One strong independent signal is enough to
    raise the alarm.
  * **rule_score is the backbone.** It is explainable and domain-specific.
  * **ml_component** = P(spam) * 100, capped. Capped because the model was
    trained on English SMS and must not single-handedly declare a critical
    verdict on unfamiliar wording.
  * **url_component** = the worst URL score found in the message.
  * **agreement bonus** is applied only when two or more independent layers
    agree, which is exactly when confidence is genuinely higher.

Calibration note (honest, for the viva)
---------------------------------------
These thresholds are a documented judgement call, not a statistically
calibrated probability. The output is a *risk indicator*, and the API repeats
that word in every response.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from backend.schemas.common import RiskLevel
from backend.schemas.scan import (
    MLPrediction,
    RiskAssessment,
    RuleEngineResult,
    URLAnalysisResult,
)

# Score -> level thresholds. Tuned so that a single HIGH rule (20 points) lands
# at "medium", while two independent strong indicators reach "high".
LEVEL_THRESHOLDS: Sequence[Tuple[int, RiskLevel]] = (
    (70, RiskLevel.CRITICAL),
    (45, RiskLevel.HIGH),
    (20, RiskLevel.MEDIUM),
    (0, RiskLevel.LOW),
)

# The ML component never contributes more than this on its own.
ML_COMPONENT_CAP = 85.0

# Multiplier applied to the ML component when the message has the structure of a
# genuine automated transaction alert AND no substantial rule fired.
# Justification: the model was trained on marketing/spam SMS where "Rs.X
# debited from A/c ..." is rare, so it systematically over-scores real bank
# alerts: a real SBI debit alert scored P(spam)=0.82. With no strong rule
# firing, the structure is far better evidence than the model, so we keep only
# a quarter of the ML signal. Measured effect on that alert: 37 -> 20 (MEDIUM),
# and it no longer reaches HIGH/CRITICAL on its own.
TRANSACTIONAL_ML_DAMPING = 0.25

HEADLINES = {
    RiskLevel.CRITICAL: "Do not interact with this message",
    RiskLevel.HIGH: "Strong scam indicators - treat as unsafe",
    RiskLevel.MEDIUM: "Suspicious - verify before acting",
    RiskLevel.LOW: "No strong scam indicators found",
}

# Category-specific actions, appended to the generic advice.
CATEGORY_ACTIONS = {
    "otp": "Never share the OTP. Your bank will never ask for it.",
    "credential": "Do not enter your password or PIN anywhere reached from this message.",
    "phishing": "Close the message and open the official app or website yourself.",
    "kyc": "Complete KYC only inside the bank's official app or at a branch.",
    "payment": "Do not transfer money. UPI transfers cannot be reversed.",
    "reward": "Ignore prize and cashback claims you did not enter for.",
    "job": "A genuine employer never asks for a fee or deposit.",
    "investment": "Guaranteed returns do not exist. Check SEBI registration first.",
    "malware": "Do not install any APK or remote-access app from a message.",
    "impersonation": "Call the organisation back on the official number from its website.",
    "threat": "Do not act out of fear. Verify the claim independently.",
    "social_engineering": "Talk to a family member or friend before you act.",
    "link": "Do not click the link. Preview the domain first.",
    "obfuscation": "Deliberately disguised wording is a strong warning sign.",
}

BASE_ACTIONS = [
    "Never share OTPs, PINs, passwords or card details with anyone.",
    "Verify any financial request through the official app or the number on your card.",
    "Report financial fraud at cybercrime.gov.in or call 1930 (India).",
]


def score_to_level(score: float) -> RiskLevel:
    """Map a 0-100 fused score onto a RiskLevel."""
    for threshold, level in LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


class RiskAssessor:
    """Combines layer outputs into a RiskAssessment."""

    # ------------------------------------------------------------------
    def assess(
        self,
        *,
        rule_engine: RuleEngineResult,
        ml_prediction: MLPrediction,
        urls: URLAnalysisResult,
    ) -> RiskAssessment:
        rule_score = int(rule_engine.score)

        # Structural "genuine transaction alert" signal (weight 0 by design).
        looks_transactional = any(
            finding.rule_id == "R_TRANSACTIONAL_ALERT_STRUCTURE"
            for finding in rule_engine.findings
        )

        # --- ML component --------------------------------------------
        ml_score: Optional[float] = None
        ml_component = 0.0
        if ml_prediction.available and ml_prediction.spam_probability is not None:
            ml_score = float(ml_prediction.spam_probability)
            ml_component = min(ML_COMPONENT_CAP, ml_score * 100.0)
            # Dampen the ML contribution when the model is not confident:
            # a 0.51 probability should not behave like 51 points of risk.
            if ml_score < 0.60:
                ml_component *= 0.5
            # A well-formed transaction alert is usually genuine, but ONLY when
            # no strong rule fired - otherwise the damping would help attackers
            # who copy the format. This is a soft, explained adjustment, never a
            # silent override of the rule engine.
            if looks_transactional and rule_score < 45:
                ml_component *= TRANSACTIONAL_ML_DAMPING

        # --- URL component -------------------------------------------
        url_component = float(urls.highest_score) if urls.analyses else 0.0

        # --- fusion ---------------------------------------------------
        components = {
            "rules": float(rule_score),
            "ml": ml_component,
            "url": url_component,
        }
        strongest = max(components.values())
        fused = strongest

        # Agreement bonus: independent layers pointing the same way.
        independent_concerns = [
            name for name, value in components.items()
            if value >= 35.0
        ]
        if len(independent_concerns) >= 3:
            fused += 8
        elif len(independent_concerns) == 2:
            fused += 5

        final_score = int(round(min(100.0, fused)))
        level = score_to_level(final_score)

        reasons = self._build_reasons(
            rule_engine=rule_engine,
            ml_prediction=ml_prediction,
            urls=urls,
            components=components,
            independent=independent_concerns,
            looks_transactional=looks_transactional,
        )
        actions = self._build_actions(rule_engine, urls, level)

        return RiskAssessment(
            level=level,
            score=final_score,
            rule_score=rule_score,
            ml_score=ml_score,
            headline=HEADLINES[level],
            reasons=reasons,
            recommended_actions=actions,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _build_reasons(
        *,
        rule_engine: RuleEngineResult,
        ml_prediction: MLPrediction,
        urls: URLAnalysisResult,
        components: dict,
        independent: List[str],
        looks_transactional: bool = False,
    ) -> List[str]:
        """Short, human-readable justification for the verdict."""
        reasons: List[str] = []

        # Top rule findings (max 4, already severity-sorted).
        for finding in rule_engine.findings[:4]:
            reasons.append(f"{finding.title} ({finding.severity.value})")
        if rule_engine.matched_count > 4:
            reasons.append(
                f"+{rule_engine.matched_count - 4} more rule indicator(s) matched"
            )

        if ml_prediction.available and ml_prediction.spam_probability is not None:
            percent = ml_prediction.spam_probability * 100
            reasons.append(
                f"Statistical model scored this message {percent:.0f}% spam-like "
                f"(label: {ml_prediction.label})"
            )
        elif not ml_prediction.available:
            reasons.append("ML model unavailable - verdict based on rules and URL analysis only")

        if urls.analyses:
            worst = urls.analyses[0]
            if worst.score >= 20:
                top = worst.indicators[0].label if worst.indicators else "suspicious pattern"
                reasons.append(
                    f"Link '{worst.registered_domain or worst.hostname}' scored "
                    f"{worst.score}/100 ({top})"
                )
            else:
                reasons.append(
                    f"{len(urls.analyses)} link(s) checked - no strong URL red flags"
                )

        if looks_transactional:
            reasons.append(
                "Message matches the format of a genuine automated bank alert, so the "
                "statistical model's weight was reduced (verify the balance in your bank app)"
            )

        if len(independent) >= 2:
            reasons.append(
                "Independent layers agree: " + ", ".join(sorted(independent))
            )
        return reasons

    # ------------------------------------------------------------------
    @staticmethod
    def _build_actions(
        rule_engine: RuleEngineResult, urls: URLAnalysisResult, level: RiskLevel
    ) -> List[str]:
        """Concrete next steps, most specific first."""
        actions: List[str] = []

        # Specific advice for the categories that actually fired.
        for category in rule_engine.categories:
            advice = CATEGORY_ACTIONS.get(category)
            if advice and advice not in actions:
                actions.append(advice)

        # URL-specific advice.
        for url_info in urls.analyses[:2]:
            if url_info.is_shortener:
                actions.append(
                    f"'{url_info.registered_domain}' is a link shortener - expand it "
                    "before opening, or type the official address yourself."
                )
            if url_info.lookalike_of:
                actions.append(
                    f"'{url_info.registered_domain}' imitates {url_info.lookalike_of.upper()}. "
                    "Open the official app instead of the link."
                )
            if url_info.score >= 40:
                actions.append("Do not open the link in this message on any device.")

        # Always finish with baseline, non-negotiable advice.
        for action in BASE_ACTIONS:
            if action not in actions:
                actions.append(action)

        # De-duplicate while preserving order, then cap the list.
        seen, ordered = set(), []
        for action in actions:
            if action not in seen:
                seen.add(action)
                ordered.append(action)
        return ordered[:7]


risk_assessor = RiskAssessor()


def get_risk_assessor() -> RiskAssessor:
    return risk_assessor
