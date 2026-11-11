"""
ScamShield AI - ml/preprocessing/normalize.py
=============================================
Text normalisation utilities shared by the rule engine, the URL analyser and
the ML pipeline.

Why a dedicated module?
-----------------------
Scammers deliberately obfuscate text so naive keyword matching fails:

    "URGENT!!!"                 -> shouting + urgency
    "K.Y.C update"              -> dots inside the word
    "acc0unt bl0cked"           -> leetspeak digits
    "urgeeeent"                 -> repeated characters
    "click hxxp://sbi-verify"   -> disguised scheme
    "аpple.com"                 -> Cyrillic 'а' homoglyph

We therefore produce TWO views of every message:

  1. `normalize()`      - a faithful, readable clean-up (used for display,
                          hashing and the ML model).
  2. `canonicalize()`   - an aggressive de-obfuscated form used ONLY for
                          pattern matching. We never show it to the user.

Keeping them separate matters: the ML model is trained on *lightly* cleaned
text (like real SMS), while the rule engine benefits from aggressive
de-obfuscation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

# ---------------------------------------------------------------------------
# Character-level clean-up
# ---------------------------------------------------------------------------
# Zero-width and direction-control characters used to break up keywords.
_INVISIBLE_CHARS = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]")

# Common Cyrillic/Greek homoglyphs that look identical to Latin letters.
_HOMOGLYPHS = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
        "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "ν": "v", "α": "a",
        "ο": "o", "ρ": "p", "τ": "t", "А": "A", "В": "B", "Е": "E", "К": "K",
        "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
    }
)

# Leetspeak substitutions used for the matching view ONLY.
# Restriction: applied per-word and only when that word already contains at
# least one letter. Without this guard "24 hrs" would become "2a hrs" and an
# OTP like "482913" would become "ab2gie" - destroying real numbers.
_LEET_DIGITS = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g"}
)
_HAS_LETTER = re.compile(r"[a-z]")

# Repeated LETTERS only: "urgeeeent" -> "urgent", "nowww" -> "now".
# Digits are excluded so "1000" and "999999" survive intact.
_REPEATS = re.compile(r"([a-z])\1{2,}")
# Dotted/spaced letters: "K.Y.C", "a c c o u n t", "v-e-r-i-f-y"
_DOTTED = re.compile(r"\b(?:[a-z][.\-_* ]){2,}[a-z]\b", re.IGNORECASE)

# Full URLs, including the disguised "hxxp" convention used in threat reports.
URL_RE = re.compile(
    r"""(?xi)
    \b(?:
        h(?:tt|xx)ps?://[^\s<>"')]+        # http(s):// or hxxp://
      | www\.[^\s<>"')]+                   # www.example.com/path
      | (?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+
        (?:com|net|org|in|co|io|xyz|top|club|site|online|shop|app|info|link|
           live|pro|biz|me|cc|tv|ru|cn|tk|ml|ga|cf|gq|work|icu|buzz|cam|
           sbs|rest|zip|mov|dev|store|website|space|fun|monster|quest|cfd|
           cyou|loan|download|stream|win|bid|date|review|country|kim|party|
           science|gdn|men|click|[a-z]{2})
        (?:/[^\s<>"')]*)?                  # optional path
    )
    """,
)

# UPI VPA: name@handle (handle looks like a bank/PSP code).
UPI_RE = re.compile(
    r"\b[a-z0-9._\-]{2,}@(?:ok(?:axis|hdfcbank|icici|sbi)|ybl|paytm|ibl|axl|apl|"
    r"upi|airtel|fbl|jio|sbi|hdfcbank|icici|kotak|yesbank|idfcbank|barodampay|"
    r"pnb|cnrb|dbs|naviaxis)\b",
    re.IGNORECASE,
)

_WHITESPACE = re.compile(r"\s+")
# Emoji / symbol soup that carries no lexical meaning.
_NON_TEXT = re.compile(r"[^\w\s@./:\-+]", re.UNICODE)


def normalize(text: str) -> str:
    """
    Light, faithful clean-up.

    Steps: NFKC unicode normalisation -> remove invisible characters -> map
    homoglyphs -> collapse whitespace. Case and punctuation are preserved
    because they carry signal (SHOUTING, "!!!", "₹").

    This is the variant used for display and for the ML model.
    """
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = _INVISIBLE_CHARS.sub("", cleaned)
    cleaned = cleaned.translate(_HOMOGLYPHS)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _WHITESPACE.sub(" ", cleaned)
    return cleaned.strip()


def _fold_leetspeak(token: str) -> str:
    """
    Fold digit-for-letter substitutions inside a single token.

    Guard rails (each one learned the hard way):
      * token must contain at least 3 letters        -> "acc0unt" yes, "24" no
      * letters must be at least as many as digits   -> "Rs.1,250.00" is money
      * tokens containing '@' are left alone         -> UPI IDs like
        9876543210@ybl must survive for the payment rules
    """
    if "@" in token or not _HAS_LETTER.search(token):
        return token
    letters = sum(1 for c in token if c.isalpha())
    digits = sum(1 for c in token if c.isdigit())
    if letters < 3 or letters < digits:
        return token
    return token.translate(_LEET_DIGITS)


def canonicalize(text: str) -> str:
    """
    Aggressive, de-obfuscated lowercase form used for pattern matching only.

    * lowercase
    * leetspeak folded ("0tp" -> "otp", "acc0unt" -> "account")
    * repeated characters collapsed ("urgeeeent" -> "urgent")
    * dotted acronyms joined ("k.y.c" -> "kyc", "v e r i f y" -> "verify")
    * "hxxp" -> "http" so URL rules and text rules agree
    """
    if not text:
        return ""
    base = normalize(text).lower()
    base = " ".join(_fold_leetspeak(token) for token in base.split())
    base = _REPEATS.sub(r"\1", base)
    base = base.replace("hxxp", "http")

    def _join_dotted(match: re.Match) -> str:
        return re.sub(r"[.\-_* ]", "", match.group(0))

    base = _DOTTED.sub(_join_dotted, base)
    return _WHITESPACE.sub(" ", base).strip()


def extract_urls(text: str) -> List[str]:
    """
    Return every URL found in the text, de-duplicated, order preserved.

    Note: this only EXTRACTS. Deciding whether a URL is dangerous is the job of
    the URL analyser (Phase 5), which never visits the link.
    """
    if not text:
        return []
    found = []
    seen = set()
    for match in URL_RE.finditer(text):
        candidate = match.group(0).rstrip(".,;:!?)]}\"'")
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            found.append(candidate)
    return found


def extract_upi_ids(text: str) -> List[str]:
    """UPI virtual payment addresses (VPAs) mentioned in the text."""
    if not text:
        return []
    seen, ordered = set(), []
    for match in UPI_RE.finditer(normalize(text)):
        value = match.group(0).lower()
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def strip_urls(text: str) -> str:
    """Replace URLs with a token so the ML model sees structure, not content."""
    return URL_RE.sub(" <url> ", text) if text else ""


def word_tokens(text: str) -> List[str]:
    """
    Simple, dependency-free tokenizer.

    Deliberately basic: the ML pipeline uses TF-IDF over cleaned text, so we
    only need letters/digits here.
    """
    return re.findall(r"[a-zA-Z]+", canonicalize(text))


def uppercase_ratio(text: str) -> float:
    """
    Share of alphabetic characters that are uppercase (0.0-1.0).

    Used by the "shouting" rule: scam SMS often look like
    "URGENT! YOUR ACCOUNT WILL BE BLOCKED".
    """
    letters = [c for c in text or "" if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def exclamation_count(text: str) -> int:
    return (text or "").count("!")


def digit_ratio(text: str) -> float:
    chars = [c for c in (text or "") if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if c.isdigit()) / len(chars)


if __name__ == "__main__":  # python -m ml.preprocessing.normalize
    demo = (
        "URGENT!!! Your K.Y.C is suspended. Acc0unt will be bl0cked in 24 hrs. "
        "Verify at hxxp://sbi-verify.xyz/login and share your OTP is 482913"
    )
    print("normalize  :", normalize(demo))
    print("canonical  :", canonicalize(demo))
    print("urls       :", extract_urls(demo))
    print("upper ratio:", round(uppercase_ratio(demo), 3))
    print("dotted     :", canonicalize("K.Y.C and v-e-r-i-f-y now"))
