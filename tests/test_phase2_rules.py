"""
ScamShield AI - tests/test_phase2_rules.py
==========================================
Tests for text normalisation and the rule-based detection engine.

Run:  pytest tests/test_phase2_rules.py -v
"""

from __future__ import annotations

import pytest

from ml.preprocessing.normalize import (
    canonicalize,
    extract_upi_ids,
    extract_urls,
    normalize,
    uppercase_ratio,
)


class TestNormalization:
    def test_homoglyphs_are_mapped(self):
        """Cyrillic 'а' in 'аpple' must become ASCII 'a'."""
        assert normalize("аpple") == "apple"

    def test_invisible_chars_removed(self):
        # A zero-width space is inserted *inside* the word: "ur<ZWSP>gent".
        assert normalize("ur\u200bgent") == "urgent"

    def test_zero_width_space_cannot_hide_a_keyword(self):
        from ml.preprocessing.normalize import canonicalize

        assert "otp" in canonicalize("share your o\u200btp now")

    def test_leetspeak_folded_in_words(self):
        assert "account" in canonicalize("Acc0unt bl0cked")

    def test_numbers_are_not_mangled(self):
        """Regression test: leetspeak folding once turned 24 into 2a."""
        assert "24" in canonicalize("blocked in 24 hrs")
        assert "482913" in canonicalize("your OTP is 482913")

    def test_money_amounts_survive(self):
        assert "1,250.00" in canonicalize("Rs.1,250.00 debited")

    def test_upi_ids_survive_canonicalisation(self):
        assert "9876543210@ybl" in canonicalize("pay to 9876543210@ybl now")

    def test_dotted_acronyms_joined(self):
        assert "kyc" in canonicalize("K.Y.C update")
        assert "verify" in canonicalize("v-e-r-i-f-y")

    def test_repeated_letters_collapsed(self):
        assert "urgent" in canonicalize("urgeeeent")

    def test_hxxp_becomes_http(self):
        assert "http://" in canonicalize("hxxp://evil.xyz")

    def test_url_extraction(self):
        text = "click http://a.xyz/x and https://b.com/y, then www.c.in"
        urls = extract_urls(text)
        assert len(urls) == 3
        assert urls[0] == "http://a.xyz/x"
        # Trailing commas must not be swallowed.
        assert urls[1] == "https://b.com/y"

    def test_url_extraction_deduplicates(self):
        assert len(extract_urls("http://a.xyz http://a.xyz")) == 1

    def test_upi_extraction(self):
        assert extract_upi_ids("pay 9876543210@ybl now") == ["9876543210@ybl"]

    def test_uppercase_ratio(self):
        assert uppercase_ratio("URGENT NOW") == 1.0
        assert uppercase_ratio("urgent now") == 0.0
        assert uppercase_ratio("") == 0.0


class TestRuleEngine:
    @pytest.fixture(autouse=True)
    def _engine(self):
        from backend.services.rule_engine import RuleEngine

        self.engine = RuleEngine()

    def _ids(self, text: str):
        return {finding.rule_id for finding in self.engine.evaluate(text)}

    # --- positive detection -------------------------------------------
    def test_otp_share_request_is_critical(self):
        result = self.engine.analyse("Please share the OTP you just received to verify your account.")
        ids = {f.rule_id for f in result.findings}
        assert "R_OTP_SHARE_REQUEST" in ids
        assert result.risk_level.value in {"high", "critical"}

    def test_kyc_scam_detected(self):
        assert "R_KYC_SCAM" in self._ids(
            "Dear customer your KYC is suspended, update immediately"
        )

    def test_kyc_detected_even_when_obfuscated(self):
        assert "R_KYC_SCAM" in self._ids("Your K.Y.C is pending, complete it now")

    def test_urgency_detected(self):
        assert "R_URGENCY_LANGUAGE" in self._ids("Act immediately within 24 hours")

    def test_threat_detected(self):
        assert "R_THREAT_LANGUAGE" in self._ids("Your account will be blocked today")

    def test_password_request_detected(self):
        assert "R_PASSWORD_REQUEST" in self._ids("Please share your net banking password")

    def test_lottery_detected(self):
        assert "R_LOTTERY_PRIZE" in self._ids("Congratulations you have won a lucky draw prize")

    def test_fake_job_detected(self):
        assert "R_FAKE_JOB_OFFER" in self._ids(
            "Work from home and earn Rs 5000 per day, no experience needed"
        )

    def test_upi_payment_request_detected(self):
        assert "R_UPI_PAYMENT_REQUEST" in self._ids("Please pay Rs 2000 to my UPI id")

    def test_qr_collect_detected(self):
        assert "R_COLLECT_REQUEST" in self._ids("Scan this QR code to receive your refund")

    def test_shortener_detected(self):
        assert "R_SHORTENED_LINK" in self._ids("Verify here http://bit.ly/abc123")

    def test_ip_link_detected(self):
        assert "R_IP_LINK" in self._ids("Login at http://192.168.1.9/bank")

    def test_apk_download_detected(self):
        ids = self._ids("Install this APK to update your KYC")
        assert "R_APK_OR_FILE_DOWNLOAD" in ids

    def test_remote_access_tool_detected(self):
        assert "R_APK_OR_FILE_DOWNLOAD" in self._ids("Install AnyDesk and share your screen")

    def test_secrecy_demand_detected(self):
        assert "R_SECRECY_DEMAND" in self._ids("Do not tell anyone about this call")

    def test_legal_impersonation_detected(self):
        assert "R_LEGAL_IMPERSONATION" in self._ids("This is CBI officer, you are under digital arrest")

    def test_mule_account_detected(self):
        assert "R_MULE_ACCOUNT" in self._ids(
            "Use your bank account to receive payments, you will get 10% commission"
        )

    def test_investment_guarantee_detected(self):
        assert "R_INVESTMENT_GUARANTEE" in self._ids("Guaranteed 30% risk-free profit in crypto")

    def test_hinglish_detected_by_curated_rules(self):
        ids = self._ids("Aapka account band ho jayega, turant OTP batao")
        assert "R_OTP_SHARE_REQUEST" in ids
        assert "R_HINDI_HINGLISH_SIGNALS" in ids

    def test_devanagari_detected(self):
        assert "R_HINDI_HINGLISH_SIGNALS" in self._ids("आपका खाता बंद हो जाएगा, तुरंत केवाईसी करें")

    # --- negative / precision -----------------------------------------
    def test_benign_chat_scores_zero(self):
        result = self.engine.analyse("Hi Rahul, are we still meeting at 6 pm near the metro?")
        assert result.score == 0
        assert result.risk_level.value == "low"
        assert result.findings == []

    def test_empty_input_is_safe(self):
        result = self.engine.analyse("")
        assert result.score == 0
        assert result.matched_count == 0

    def test_genuine_debit_alert_not_escalated(self):
        """Regression: a real SBI alert must not be scored as a scam."""
        result = self.engine.analyse(
            "Rs.1250.00 debited from A/c XX1234 on 09-11-26 to VPA rahul@okhdfcbank. "
            "Balance 12000.00. Not you? Call the number on your card."
        )
        assert result.score <= 15
        assert result.risk_level.value == "low"

    def test_completed_transaction_vpa_not_flagged_as_payment_request(self):
        ids = self._ids("Rs.500 debited from A/c XX99 to VPA shop@okaxis. Balance 100.")
        assert "R_UNKNOWN_ACCOUNT" not in ids

    def test_payment_request_with_vpa_is_flagged(self):
        ids = self._ids("Please pay Rs 5000 to 9876543210@ybl immediately")
        assert "R_UNKNOWN_ACCOUNT" in ids or "R_UPI_PAYMENT_REQUEST" in ids

    # --- scoring behaviour --------------------------------------------
    def test_score_is_bounded(self):
        worst = (
            "URGENT! Your KYC is suspended. Share your OTP and password now. "
            "Click http://sbi-kyc-verify.xyz/login or account blocked. "
            "Pay Rs 5000 to 9876543210@ybl. Install this APK. Do not tell anyone. "
            "You have won a lottery prize! This is CBI, digital arrest. "
            "Work from home earn Rs 5000 per day registration fee. "
            "Guaranteed 30% risk-free profit."
        )
        result = self.engine.analyse(worst)
        assert 0 <= result.score <= 100
        assert result.risk_level.value == "critical"

    def test_repeated_urgency_does_not_stack_unbounded(self):
        """
        Category de-duplication: saying 'urgent' five times must not add 5x12.
        """
        once = self.engine.analyse("This is urgent, please respond")
        many = self.engine.analyse(
            "This is urgent, urgent, urgent, immediately, right now, act now"
        )
        assert many.score < once.score + 40

    def test_reasons_are_generated(self):
        result = self.engine.analyse("Share your OTP now")
        reasons = getattr(result, "_reasons", [])
        assert reasons
        assert any("OTP" in reason for reason in reasons)

    def test_combinations_add_weight(self):
        """KYC + link must score higher than either alone."""
        kyc_only = self.engine.analyse("Your KYC is suspended")
        link_only = self.engine.analyse("Visit http://example.com/page")
        both = self.engine.analyse("Your KYC is suspended, visit http://sbi-kyc.xyz/login")
        assert both.score > max(kyc_only.score, link_only.score)

    def test_findings_sorted_by_severity(self):
        result = self.engine.analyse(
            "Dear customer, urgent: your KYC is blocked, share the OTP at http://bit.ly/x"
        )
        weights = [f.severity.weight for f in result.findings]
        assert weights == sorted(weights, reverse=True)

    def test_rule_catalogue_is_exposed(self):
        from backend.services.rule_catalog import catalogue_summary

        summary = catalogue_summary()
        assert len(summary) >= 30
        ids = {entry["rule_id"] for entry in summary}
        assert len(ids) == len(summary), "rule ids must be unique"

    def test_all_rule_patterns_compile(self):
        """A bad regex must fail here, not in production."""
        import re

        from backend.services.rule_catalog import ALL_RULES

        for rule in ALL_RULES:
            for pattern in rule.patterns:
                re.compile(pattern)
