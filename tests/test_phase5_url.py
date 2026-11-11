"""
ScamShield AI - tests/test_phase5_url.py
========================================
Tests for the non-invasive URL analyser.

The most important test here is `test_never_makes_network_calls`, which proves
the safety claim in the module docstring instead of just asserting it in prose.
"""

from __future__ import annotations

import pytest

from backend.services.url_analyzer import URLAnalyzer, url_analyzer


def codes(url: str) -> set[str]:
    return {indicator.code for indicator in url_analyzer.analyse(url).indicators}


class TestSafety:
    def test_never_makes_network_calls(self, monkeypatch):
        """
        Patch socket.connect and assert it is never called.

        If anyone later adds a DNS lookup or an HTTP request to the analyser,
        this test fails immediately.
        """
        import socket

        called = {"count": 0}

        def guard(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("URL analyser attempted a network connection")

        monkeypatch.setattr(socket.socket, "connect", guard)
        monkeypatch.setattr(socket, "create_connection", guard)

        for url in [
            "http://sbi-kyc-verify.xyz/login",
            "https://bit.ly/abc",
            "http://192.168.1.1/x",
            "https://аpple.com/verify",
        ]:
            url_analyzer.analyse(url)

        assert called["count"] == 0


class TestSchemeChecks:
    def test_https_not_flagged(self):
        assert "no_https" not in codes("https://example.com/page")

    def test_http_flagged(self):
        assert "no_https" in codes("http://example.com/page")

    def test_javascript_scheme_is_critical(self):
        analysis = url_analyzer.analyse("javascript:alert(document.cookie)")
        assert "dangerous_scheme" in {i.code for i in analysis.indicators}
        assert analysis.score >= 35

    def test_data_scheme_is_critical(self):
        assert "dangerous_scheme" in codes("data:text/html;base64,PHNjcmlwdD4=")


class TestHostChecks:
    def test_ip_host_flagged(self):
        analysis = url_analyzer.analyse("http://192.168.4.7/bank")
        assert analysis.is_ip_address is True
        assert "ip_address_host" in {i.code for i in analysis.indicators}

    def test_ip_host_has_no_invented_tld(self):
        """Regression: '192.168.4.7' must not be parsed as TLD '7'."""
        analysis = url_analyzer.analyse("http://10.20.30.40/login")
        assert analysis.tld == ""
        assert analysis.registered_domain == "10.20.30.40"

    def test_shortener_flagged(self):
        assert "shortener" in codes("https://bit.ly/x9k2")

    def test_suspicious_tld_flagged(self):
        assert "suspicious_tld" in codes("https://something.xyz/page")

    def test_deep_subdomains_flagged(self):
        assert "deep_subdomains" in codes("https://a.b.c.d.example.com/x")

    def test_unusual_port_flagged(self):
        assert "unusual_port" in codes("http://example.com:8080/x")

    def test_userinfo_trick_critical(self):
        """http://sbi.co.in@evil.xyz actually connects to evil.xyz."""
        analysis = url_analyzer.analyse("http://sbi.co.in@evil.xyz/login")
        assert "userinfo_trick" in {i.code for i in analysis.indicators}
        assert analysis.hostname == "evil.xyz"

    def test_punycode_flagged(self):
        assert "punycode" in codes("https://xn--pypal-4ve.com/login")

    def test_homoglyph_flagged(self):
        assert "homoglyph" in codes("https://аpple.com/verify")  # Cyrillic 'а'

    def test_executable_download_critical(self):
        analysis = url_analyzer.analyse("https://paytm-offer.apk")
        assert "executable_download" in {i.code for i in analysis.indicators}

    def test_double_extension_flagged(self):
        assert "executable_download" in codes("https://host.xyz/invoice.pdf.exe")


class TestBrandImpersonation:
    @pytest.mark.parametrize(
        "url, brand",
        [
            ("http://sbi-kyc-verify.xyz/login", "sbi"),
            ("https://hdfcbank-login.top/secure", "hdfc"),
            ("https://paytm-offer.apk", "paytm"),
            ("https://amazon-rewards.club/claim", "amazon"),
        ],
    )
    def test_lookalike_detected(self, url, brand):
        analysis = url_analyzer.analyse(url)
        assert analysis.lookalike_of == brand
        assert "brand_lookalike" in {i.code for i in analysis.indicators}

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.sbi.co.in/web/personal-banking",
            "https://www.hdfcbank.com/personal/save",
            "https://www.icicibank.com/",
            "https://paytm.com/recharge",
            "https://www.google.com/search?q=test",
            "https://www.amazon.in/deals",
        ],
    )
    def test_genuine_domains_not_flagged(self, url):
        analysis = url_analyzer.analyse(url)
        assert analysis.lookalike_of is None
        assert analysis.score == 0, f"{url} produced {[i.code for i in analysis.indicators]}"

    def test_punycode_brand_lookalike(self):
        analysis = url_analyzer.analyse("https://xn--pypal-4ve.com/login")
        assert analysis.lookalike_of == "paypal"


class TestKeywordAndStructure:
    def test_phishing_keywords_detected(self):
        assert "phishing_keywords" in codes("https://example.com/account/verify/login")

    def test_long_url_flagged(self):
        assert "long_url" in codes("https://example.com/" + "a" * 120)

    def test_clean_url_scores_zero(self):
        analysis = url_analyzer.analyse("https://www.wikipedia.org/wiki/Phishing")
        assert analysis.score == 0
        assert analysis.indicators == []


class TestTextIntegration:
    def test_extracts_every_url_in_a_message(self):
        analyses, highest = url_analyzer.analyse_text(
            "See http://a.xyz/1 and https://b.com/2 for details"
        )
        assert len(analyses) == 2
        assert highest > 0

    def test_message_without_urls(self):
        analyses, highest = url_analyzer.analyse_text("no links here at all")
        assert analyses == []
        assert highest == 0

    def test_analyses_sorted_by_score(self):
        analyses, _ = url_analyzer.analyse_text(
            "https://www.google.com and http://sbi-kyc-verify.xyz/login"
        )
        assert analyses[0].score >= analyses[-1].score

    def test_bare_domain_gets_scheme(self):
        analysis = url_analyzer.analyse("sbi-kyc-verify.xyz/login")
        assert analysis.hostname == "sbi-kyc-verify.xyz"
        assert analysis.is_https is False


class TestAnalyzerContract:
    def test_score_is_bounded(self):
        for url in ["https://a.b.c.d.e.verify-login-secure-account.xyz:8080/x?y=1", "http://192.1.1.1@evil.tk/kyc"]:
            assert 0 <= url_analyzer.analyse(url).score <= 100

    def test_indicators_sorted_by_severity(self):
        analysis = url_analyzer.analyse("http://sbi-kyc-verify.xyz/login")
        weights = [indicator.severity.weight for indicator in analysis.indicators]
        assert weights == sorted(weights, reverse=True)

    def test_malformed_url_does_not_raise(self):
        for bad in ["http://[::1", "://", "ht!tp://x", ""]:
            analysis = url_analyzer.analyse(bad)
            assert 0 <= analysis.score <= 100

    def test_idempotent(self):
        a = url_analyzer.analyse("http://sbi-kyc-verify.xyz/login")
        b = url_analyzer.analyse("http://sbi-kyc-verify.xyz/login")
        assert a.model_dump() == b.model_dump()
