"""
ScamShield AI - backend/services/url_analyzer.py
================================================
Static, non-invasive URL analysis.

SAFETY STATEMENT (also shown in the UI)
---------------------------------------
This module NEVER connects to the URL. It performs no DNS lookup, sends no
HTTP request, and does not resolve the domain. It only inspects the *text* of
the URL. Consequences, stated honestly:

  * We cannot know whether a site is currently serving malware.
  * We cannot know whether a brand domain is genuine but compromised.
  * Pattern analysis produces false positives (e.g. a legitimate new startup
    on a cheap TLD) and false negatives (a phishing page on a hijacked
    legitimate domain).
  * A low score therefore means "no known pattern matched", NOT "safe".

If live reputation data is needed later, plug a reputation API (Google Safe
Browsing, VirusTotal) in behind this same interface - see docs/future_scope.md.

What is checked
---------------
scheme (HTTPS), IP-literal hosts, URL shorteners, punycode/IDN homoglyphs,
suspicious TLDs, subdomain depth, brand-lookalike tokens, phishing keywords in
the host and path, excessive length/subdomains, embedded credentials, unusual
ports, double extensions, encoded characters, and data: URIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from backend.schemas.common import Severity
from backend.schemas.scan import URLIndicator, URLInfo
from ml.preprocessing.normalize import extract_urls, normalize

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
#: Link shorteners hide the destination. Not inherently malicious, but they
#: remove the user's ability to judge the domain before clicking.
SHORTENERS = {
    "bit.ly", "bit.do", "tinyurl.com", "tiny.cc", "t.co", "goo.gl", "ow.ly",
    "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorte.st", "adf.ly",
    "t.ly", "rb.gy", "shorturl.at", "clck.ru", "s.id", "chip.ly", "lnkd.in",
    "bl.ink", "short.io", "v.gd", "soo.gd", "x.gd", "1url.com", "shrtco.de",
    "qr.ae", "lnk.to", "urlz.fr", "trib.al",
}

#: TLDs with a high abuse rate (cheap or free registration, weak identity
#: checks). Source: abuse statistics published by Spamhaus/Interisle.
SUSPICIOUS_TLDS = {
    "xyz", "top", "club", "icu", "buzz", "cam", "sbs", "rest", "monster",
    "quest", "cfd", "cyou", "loan", "download", "stream", "win", "bid",
    "date", "review", "country", "kim", "party", "science", "gdn", "men",
    "click", "tk", "ml", "ga", "cf", "gq", "work", "life", "zip", "mov",
    "su", "ws", "biz", "info", "online", "site", "space", "fun", "pro",
}

#: Brands frequently impersonated in Indian phishing. `legit` lists the real
#: registered domains, used to avoid flagging the brand's own site.
BRANDS: Dict[str, List[str]] = {
    "sbi": ["sbi.co.in", "onlinesbi.sbi", "sbiyono.sbi", "sbicard.com"],
    "hdfc": ["hdfcbank.com", "hdfcsec.com", "hdfclife.com"],
    "icici": ["icicibank.com", "icicidirect.com"],
    "axis": ["axisbank.com", "axisbank.co.in"],
    "kotak": ["kotak.com", "kotakbank.com"],
    "pnb": ["pnbindia.in"],
    "bob": ["bankofbaroda.in"],
    "canara": ["canarabank.com"],
    "union": ["unionbankofindia.co.in"],
    "indusind": ["indusind.com"],
    "yesbank": ["yesbank.in"],
    "idfc": ["idfcfirstbank.com"],
    "paytm": ["paytm.com", "paytmbank.com"],
    "phonepe": ["phonepe.com"],
    "gpay": ["google.com", "pay.google.com"],
    "bhim": ["npci.org.in"],
    "amazon": ["amazon.in", "amazon.com"],
    "flipkart": ["flipkart.com"],
    "netflix": ["netflix.com"],
    "irctc": ["irctc.co.in", "irctc.com"],
    "uidai": ["uidai.gov.in"],
    "incometax": ["incometax.gov.in", "incometaxindia.gov.in"],
    "epfo": ["epfindia.gov.in"],
    "lic": ["licindia.in"],
    "airtel": ["airtel.in"],
    "jio": ["jio.com"],
    "vodafone": ["vodafone.in", "myvi.in"],
    "whatsapp": ["whatsapp.com"],
    "instagram": ["instagram.com"],
    "facebook": ["facebook.com"],
    "microsoft": ["microsoft.com", "live.com", "office.com"],
    "apple": ["apple.com", "icloud.com"],
    "google": ["google.com"],
    "paypal": ["paypal.com"],
    "dhl": ["dhl.com"],
    "fedex": ["fedex.com"],
    "linkedin": ["linkedin.com"],
    "telegram": ["telegram.org", "t.me"],
    "tiktok": ["tiktok.com"],
    "hsbc": ["hsbc.co.in", "hsbc.com"],
    "dmart": ["dmart.in"],
    "swiggy": ["swiggy.com", "swiggy.in"],
    "zomato": ["zomato.com"],
}

#: Words that make a *path* or *host* look like a credential-capture page.
PHISHING_KEYWORDS = {
    "login", "signin", "sign-in", "logon", "verify", "verification", "validate",
    "secure", "security", "update", "account", "auth", "authenticate", "otp",
    "kyc", "reverify", "confirm", "unlock", "reactivate", "billing", "payment",
    "wallet", "netbanking", "net-banking", "reset", "recover", "support",
    "custcare", "helpline", "refund", "claim", "reward", "winner", "offer",
    "bonus", "gift", "free", "verify-account", "suspended", "blocked",
}

#: Tokens attackers glue to brand names to sound official.
LOOKALIKE_SEPARATORS = {"verify", "kyc", "update", "login", "secure", "account",
                        "support", "help", "service", "online", "official", "care",
                        "customercare", "reverify", "auth", "alert", "notice"}

PUNYCODE_PREFIX = "xn--"

# Homoglyph characters commonly used to fake ASCII letters in IDNs.
_HOMOGLYPH_CHARS = set("аеорсухіјѕԁɡν αρτАВЕКМНОРСТХ")

#: Ports that should never appear in a consumer-facing URL.
UNUSUAL_PORTS = {"8080", "8443", "8000", "3000", "4443", "9000", "10000", "8888"}

# Indicators for executable file extensions.
RISKY_FILE_EXTENSIONS = (".apk", ".exe", ".scr", ".bat", ".cmd", ".msi",
                         ".jar", ".vbs", ".js", ".ps1", ".dll")

_TLDS_FOR_PARSING = re.compile(r"^[a-z0-9\-]+(\.[a-z0-9\-]+)+$")


# ---------------------------------------------------------------------------
# Helper structures
# ---------------------------------------------------------------------------
@dataclass
class _Signals:
    """Accumulates indicators and their raw weights before clamping to 100."""

    indicators: List[URLIndicator] = field(default_factory=list)
    score: int = 0

    def add(self, code: str, label: str, detail: str, severity: Severity, points: int) -> None:
        # Avoid duplicate codes for the same URL.
        if any(indicator.code == code for indicator in self.indicators):
            return
        self.indicators.append(
            URLIndicator(code=code, label=label, detail=detail, severity=severity)
        )
        self.score += points


def _split_host(hostname: str) -> Tuple[str, str, List[str]]:
    """
    Split a hostname into (registered_domain, tld, subdomain_labels).

    We do this with a small heuristic instead of the public-suffix list to keep
    the dependency footprint at zero. Known two-part suffixes for the markets
    we care about are handled explicitly.

        a.b.sbi.co.in -> ("sbi.co.in", "in", ["a","b"])
        paytm-kyc.xyz -> ("paytm-kyc.xyz", "xyz", [])
    """
    host = (hostname or "").lower().strip(".")
    if not host:
        return "", "", []

    parts = host.split(".")
    if len(parts) < 2:
        return host, "", []

    two_part_suffixes = {
        "co.in", "co.uk", "co.jp", "co.za", "com.au", "net.in", "org.in",
        "gov.in", "ac.in", "nic.in", "res.in", "edu.in", "firm.in", "gen.in",
        "ind.in", "com.br", "com.cn", "co.nz", "com.sg", "com.my",
    }
    last_two = ".".join(parts[-2:])
    if last_two in two_part_suffixes and len(parts) >= 3:
        registered = ".".join(parts[-3:])
        tld = last_two
        subdomains = parts[:-3]
    else:
        registered = last_two
        tld = parts[-1]
        subdomains = parts[:-2]
    return registered, tld, subdomains


#: Cyrillic/Greek -> Latin map used to unmask look-alike brands before we
#: test whether the hostname contains a protected brand name.
_HOMOGLYPH_MAP = str.maketrans({
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c",
    "\u0443": "y", "\u0445": "x", "\u0456": "i", "\u0458": "j", "\u0455": "s",
    "\u0501": "d", "\u0261": "g", "\u03bd": "v", "\u03b1": "a", "\u03bf": "o",
    "\u03c1": "p", "\u0442": "t",
})


def _dehomoglyph(value: str) -> str:
    """Map look-alike Cyrillic/Greek letters to their Latin equivalents."""
    return (value or "").translate(_HOMOGLYPH_MAP)


def _decode_punycode(hostname: str) -> str:
    """
    Turn "xn--pypal-4ve.com" into its Unicode form ("pypal.com"-ish).

    Punycode is the ASCII encoding of an internationalised domain. Attackers
    register "xn--..." domains whose decoded form imitates a brand, so we decode
    locally (pure string operation, no DNS) before the brand check.
    """
    if PUNYCODE_PREFIX not in (hostname or ""):
        return hostname or ""
    labels = []
    for label in hostname.split("."):
        if label.startswith(PUNYCODE_PREFIX):
            try:
                # The idna codec expects the FULL "xn--..." label, not the payload.
                labels.append(label.encode("ascii").decode("idna"))
            except (UnicodeError, ValueError):
                labels.append(label)          # keep the raw label if decoding fails
        else:
            labels.append(label)
    return ".".join(labels)


def _normalize_input(raw: str) -> str:
    """Add a scheme when the user pasted a bare domain."""
    candidate = (raw or "").strip()
    candidate = candidate.replace("hxxp://", "http://").replace("hxxps://", "https://")
    if candidate and not re.match(r"^[a-z][a-z0-9+.\-]*://", candidate, re.IGNORECASE):
        if re.match(r"^(?:www\.)?[a-z0-9\-]+(\.[a-z0-9\-]+)+", candidate, re.IGNORECASE):
            candidate = "http://" + candidate
    return candidate


# ---------------------------------------------------------------------------
# Main analyser
# ---------------------------------------------------------------------------
class URLAnalyzer:
    """
    Stateless URL pattern analyser.

    `analyse(url)` and `analyse_text(text)` are pure functions: no network,
    no filesystem, no randomness.
    """

    def __init__(self) -> None:
        self._brand_tokens = sorted(BRANDS.keys(), key=len, reverse=True)

    # ------------------------------------------------------------------
    def analyse(self, raw_url: str) -> URLInfo:
        """Analyse ONE url and return a populated URLInfo."""
        normalized = _normalize_input(raw_url)
        signals = _Signals()

        try:
            parts = urlsplit(normalized)
        except ValueError:
            # Malformed URL (e.g. invalid IPv6 brackets).
            signals.add(
                "malformed_url", "Malformed URL",
                "The URL could not be parsed, which is itself unusual.",
                Severity.MEDIUM, 12,
            )
            return self._build_info(
                raw_url, normalized,
                scheme="", hostname="", registered="", tld="", path="",
                signals=signals,
            )

        scheme = (parts.scheme or "").lower()
        hostname = (parts.hostname or "").lower()
        path = parts.path or ""
        url_length = len(normalized)

        # --- scheme / transport ---------------------------------------
        is_https = scheme == "https"
        if scheme in {"javascript", "data", "file", "blob"}:
            signals.add(
                "dangerous_scheme", "Dangerous URL scheme",
                f"The '{scheme}:' scheme can execute code or embed a page that "
                "hides its true origin. Never open it from a message.",
                Severity.CRITICAL, 35,
            )
            # NOTE: keyword arguments on purpose. A positional call here once
            # passed [] into `path` and raised a Pydantic ValidationError.
            return self._build_info(
                raw_url, normalized,
                scheme=scheme, hostname=hostname, registered="", tld="", path="",
                signals=signals,
            )

        if not is_https:
            signals.add(
                "no_https", "No HTTPS",
                "The connection would not be encrypted. Credentials typed on a "
                "plain-HTTP page can be intercepted.",
                Severity.MEDIUM, 12,
            )
        if scheme not in {"http", "https"}:
            signals.add(
                "unusual_scheme", "Unusual scheme",
                f"Scheme '{scheme or 'none'}' is not a normal web link.",
                Severity.MEDIUM, 10,
            )

        # --- hostname checks ------------------------------------------
        is_ip = bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", hostname))
        if is_ip:
            signals.add(
                "ip_address_host", "IP address instead of a domain",
                "Legitimate services publish domain names. A bare IP address is a "
                "common sign of a throwaway phishing host.",
                Severity.HIGH, 25,
            )
        if hostname.startswith("[") or ":" in hostname:
            signals.add(
                "ipv6_or_port_host", "Unusual host form",
                "The host contains an address form rarely used by consumer services.",
                Severity.MEDIUM, 10,
            )

        if is_ip:
            # An IPv4 literal has no registrable domain, TLD or subdomains.
            # Splitting "192.168.4.7" would invent reg="4.7"/tld="7".
            registered, tld, subdomains = hostname, "", []
        else:
            registered, tld, subdomains = _split_host(hostname)

        if registered in SHORTENERS or hostname in SHORTENERS:
            signals.add(
                "shortener", "Link shortener",
                f"{registered} hides the real destination, so you cannot judge the "
                "site before clicking.",
                Severity.MEDIUM, 15,
            )

        if PUNYCODE_PREFIX in hostname:
            signals.add(
                "punycode", "Punycode (internationalised) domain",
                "The domain uses non-Latin characters. Attackers use them to build "
                "look-alike domains (e.g. 'аpple.com' with a Cyrillic 'а').",
                Severity.HIGH, 20,
            )
        if any(char in _HOMOGLYPH_CHARS for char in hostname):
            signals.add(
                "homoglyph", "Look-alike characters in the domain",
                "The domain mixes Cyrillic/Greek letters with Latin ones to imitate a "
                "well-known brand.",
                Severity.HIGH, 22,
            )

        if tld in SUSPICIOUS_TLDS:
            signals.add(
                "suspicious_tld", "High-abuse top-level domain",
                f"'.{tld}' is cheap or free to register and is heavily used by phishing "
                "campaigns. That alone does not make this URL malicious.",
                Severity.MEDIUM, 12,
            )

        if is_ip:
            pass  # no subdomain analysis for IP literals
        elif len(subdomains) >= 3:
            signals.add(
                "deep_subdomains", "Many subdomain levels",
                f"{len(subdomains)} subdomains were used. Long chains like "
                "'sbi.secure.login.verify.xyz' are built to make the eye stop reading "
                "before the real domain.",
                Severity.HIGH, 18,
            )
        elif len(subdomains) == 2:
            signals.add(
                "nested_subdomains", "Nested subdomains",
                "Two subdomain levels - check that the real domain (just before the "
                "TLD) is the brand you expect.",
                Severity.LOW, 6,
            )

        # --- brand look-alike detection -------------------------------
        lookalike_of: Optional[str] = None
        host_without_dots = hostname.replace(".", "")
        # Unmask Cyrillic/Greek look-alikes so "аpple.com" is recognised as an
        # Apple imitation in addition to the generic homoglyph indicator.
        unmasked_host = _dehomoglyph(_decode_punycode(hostname))
        unmasked_without_dots = unmasked_host.replace(".", "")
        for brand in self._brand_tokens:
            if brand not in host_without_dots and brand not in unmasked_without_dots:
                continue
            legit_domains = BRANDS[brand]
            if registered in legit_domains or hostname in legit_domains:
                break  # the genuine domain - not a look-alike
            # The brand appears, but this is not its registered domain.
            looks_separated = any(
                f"{brand}{sep}" in host_without_dots or f"{sep}{brand}" in host_without_dots
                for sep in LOOKALIKE_SEPARATORS
            ) or registered.split(".")[0] != brand
            if looks_separated:
                lookalike_of = brand
                signals.add(
                    "brand_lookalike", f"Domain imitates '{brand.upper()}'",
                    f"The host contains the brand name '{brand}' but is registered as "
                    f"'{registered}', which is not an official domain of that brand "
                    f"(official: {', '.join(legit_domains[:2])}).",
                    Severity.HIGH, 25,
                )
            break

        # --- path / query keyword checks ------------------------------
        searchable = f"{hostname}{path}".lower()
        hits = sorted(
            {
                keyword
                for keyword in PHISHING_KEYWORDS
                if re.search(rf"(?:^|[/.\-_?&=]){re.escape(keyword)}(?:$|[/.\-_?&=])", searchable)
            }
        )
        if hits:
            severity = Severity.HIGH if len(hits) >= 2 else Severity.MEDIUM
            points = 18 if len(hits) >= 2 else 10
            signals.add(
                "phishing_keywords", "Phishing-style keywords",
                "The URL contains credential or lure words: " + ", ".join(hits[:5]),
                severity, points,
            )

        # --- structural oddities --------------------------------------
        if url_length > 100:
            signals.add(
                "long_url", "Very long URL",
                f"{url_length} characters. Excessive length is used to hide the real "
                "domain from a quick glance.",
                Severity.MEDIUM, 10,
            )
        elif url_length > 75:
            signals.add(
                "longish_url", "Long URL",
                f"{url_length} characters - longer than typical, worth a closer look.",
                Severity.LOW, 5,
            )

        if "@" in (parts.netloc or ""):
            signals.add(
                "userinfo_trick", "Credentials embedded in the URL",
                "Everything before '@' is ignored by browsers, so "
                "'http://sbi.co.in@evil.xyz' actually goes to evil.xyz.",
                Severity.CRITICAL, 30,
            )

        host_and_path = f"{hostname}{path}".lower()
        if any(ext in host_and_path for ext in RISKY_FILE_EXTENSIONS):
            signals.add(
                "executable_download", "Direct executable download",
                "The link points to an installable file. Sideloaded APKs are the "
                "delivery method for most Indian banking trojans.",
                Severity.CRITICAL, 30,
            )

        if re.search(r"\.(?:pdf|docx?|xlsx?|zip|rar)\.(?:exe|apk|scr|js)(?:$|[/?#])", host_and_path):
            signals.add(
                "double_extension", "Double file extension",
                "A file named like 'invoice.pdf.exe' is an executable disguised as a "
                "document.",
                Severity.CRITICAL, 28,
            )

        if "%" in path and re.search(r"%[0-9a-f]{2}", path, re.IGNORECASE):
            decoded_hits = [k for k in PHISHING_KEYWORDS if k in path.lower().replace("%2f", "/")]
            signals.add(
                "encoded_characters", "Percent-encoded characters in the path",
                "Encoding is often used to hide keywords from filters"
                + (f" (decodes to: {', '.join(decoded_hits[:3])})" if decoded_hits else "") + ".",
                Severity.LOW, 6,
            )

        if parts.port and str(parts.port) in UNUSUAL_PORTS:
            signals.add(
                "unusual_port", "Non-standard port",
                f"The URL uses port {parts.port}. Consumer websites rarely publish "
                "non-standard ports.",
                Severity.MEDIUM, 10,
            )

        if re.search(r"(?:\d{1,3}\.){3}\d{1,3}", hostname) and not is_ip:
            signals.add(
                "embedded_ip", "IP address embedded in the host",
                "An IP-based subdomain is a common way to keep a phishing kit alive.",
                Severity.MEDIUM, 12,
            )

        suspicious_tokens = sorted(
            {token for token in hits if token in {"verify", "kyc", "login", "otp",
                                                  "update", "secure", "account",
                                                  "refund", "claim", "reward"}}
        )

        return self._build_info(
            raw_url, normalized, scheme, hostname, registered, tld, path,
            signals,
            is_https=is_https,
            is_ip=is_ip,
            is_shortener=registered in SHORTENERS,
            subdomains=subdomains,
            url_length=url_length,
            suspicious_tokens=suspicious_tokens,
            lookalike_of=lookalike_of,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _build_info(
        raw_url: str,
        normalized: str,
        scheme: str,
        hostname: str,
        registered: str,
        tld: str,
        path: str,
        signals: _Signals,
        *,
        is_https: bool = False,
        is_ip: bool = False,
        is_shortener: bool = False,
        subdomains: Optional[List[str]] = None,
        url_length: int = 0,
        suspicious_tokens: Optional[List[str]] = None,
        lookalike_of: Optional[str] = None,
    ) -> URLInfo:
        # Sort indicators by severity so the UI shows the worst first.
        ordered = sorted(signals.indicators, key=lambda i: -i.severity.weight)
        return URLInfo(
            raw=raw_url,
            normalized=normalized,
            scheme=scheme,
            hostname=hostname,
            registered_domain=registered,
            tld=tld,
            path=path,
            is_https=is_https,
            is_ip_address=is_ip,
            is_shortener=is_shortener,
            subdomain_count=len(subdomains or []),
            url_length=url_length or len(normalized),
            suspicious_token_hits=suspicious_tokens or [],
            lookalike_of=lookalike_of,
            score=min(100, signals.score),
            indicators=ordered,
        )

    # ------------------------------------------------------------------
    def analyse_text(self, text: str) -> Tuple[List[URLInfo], int]:
        """
        Find and analyse every URL in a free-text message.

        Returns (analyses, highest_score). De-duplicated by normalised URL.
        """
        found = extract_urls(normalize(text or ""))
        analyses: List[URLInfo] = []
        seen = set()
        for candidate in found:
            info = self.analyse(candidate)
            key = info.normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            analyses.append(info)
        highest = max((info.score for info in analyses), default=0)
        analyses.sort(key=lambda info: -info.score)
        return analyses, highest


url_analyzer = URLAnalyzer()


def get_url_analyzer() -> URLAnalyzer:
    return url_analyzer
