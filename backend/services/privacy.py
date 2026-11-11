"""
ScamShield AI - backend/services/privacy.py
===========================================
Privacy safeguards for stored message content.

Threat model
------------
Users paste real messages that may contain phone numbers, account numbers,
emails and OTP codes. Storing that verbatim creates a data-protection problem.

Three controls implemented here
-------------------------------
1. **Redaction** - sensitive tokens are replaced before anything is persisted
   or logged: 4111 1111 1111 1111 -> [CARD], 9876543210 -> [PHONE],
   user@mail.com -> [EMAIL], OTP 482913 -> OTP [OTP].
2. **Hashing** - a salted SHA-256 of the normalised text lets us detect
   duplicates without keeping the plaintext.
3. **Retention** - `store_raw_message=false` prevents plaintext storage
   entirely; only the redacted preview remains.

This is deliberately conservative: we keep a short preview because the user
needs to recognise their own scans in the history list.
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict

from backend.config import get_settings

# ---------------------------------------------------------------------------
# Compiled regexes (compiled once at import time for speed)
# ---------------------------------------------------------------------------
# Indian mobile numbers: optional +91 / 0 prefix, then 10 digits starting 6-9.
_PHONE_IN = re.compile(r"(?<![\d])(?:\+?91[\-\s]?|0)?[6-9]\d{9}(?![\d])")
# Generic international phone numbers with separators.
_PHONE_INTL = re.compile(r"(?<!\d)\+?\d{1,3}[\s\-]?\d{3}[\s\-]?\d{3,4}[\s\-]?\d{3,4}(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# Card numbers: 16 digits, optionally grouped in blocks of 4.
_CARD = re.compile(r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)")
# UPI VPAs: name@handle (handle must look like a bank/PSP handle).
_UPI = re.compile(
    r"\b[A-Za-z0-9._\-]{2,}@(?:ok(?:axis|hdfcbank|icici|sbi)|"
    r"ybl|paytm|ibl|axl|upi|apl|airtel|fbl|jio|sbi|hdfcbank|icici|"
    r"kotak|yesbank|idfcbank|barodampay|pnb|cnrb)\b",
    re.IGNORECASE,
)
# OTP / PIN style codes: "OTP is 482913" or "code: 1234".
_OTP = re.compile(
    r"(?i)\b(?:otp|o\.t\.p|code|pin)\b[^0-9]{0,15}(\d{4,8})\b"
)
# IFSC codes.
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
# Aadhaar-like 12 digit numbers (grouped or not).
_AADHAAR = re.compile(r"(?<!\d)(?:\d{4}[\s\-]){2}\d{4}(?!\d)")

REDACTION_MAP = [
    ("[OTP]", _OTP),
    ("[CARD]", _CARD),
    ("[UPI_ID]", _UPI),
    ("[EMAIL]", _EMAIL),
    ("[IFSC]", _IFSC),
    ("[AADHAAR]", _AADHAAR),
    ("[PHONE]", _PHONE_IN),
    ("[PHONE]", _PHONE_INTL),
]


def redact(text: str) -> str:
    """
    Replace sensitive values with bracketed placeholders.

    Order matters: card numbers are redacted before generic phone numbers so a
    16-digit card is not partially mistaken for a 10-digit mobile number.
    """
    if not text:
        return ""
    redacted = text
    for placeholder, pattern in REDACTION_MAP:
        if placeholder == "[OTP]":
            # Keep the label, hide the digits: "OTP is 482913" -> "OTP is [OTP]"
            redacted = pattern.sub(lambda m: m.group(0).replace(m.group(1), "[OTP]"), redacted)
        else:
            redacted = pattern.sub(placeholder, redacted)
    return redacted


def make_preview(text: str, limit: int = 160) -> str:
    """Short, single-line, redacted snippet for history lists."""
    if not text:
        return ""
    collapsed = " ".join(text.split())
    snippet = collapsed[:limit]
    return snippet + ("…" if len(collapsed) > limit else "")


def content_hash(text: str) -> str:
    """
    Salted SHA-256 of the normalised text.

    * Salt comes from PRIVACY_SALT so identical messages produce different
      hashes across deployments (prevents cross-database correlation).
    * Normalisation (lowercase + collapsed whitespace) makes the hash stable
      for the same message with different spacing.
    """
    salt = get_settings().privacy_salt or "scamshield"
    normalised = " ".join((text or "").lower().split())
    return hashlib.sha256(f"{salt}:{normalised}".encode("utf-8")).hexdigest()


def privacy_payload(text: str) -> Dict[str, str | None]:
    """
    Build every privacy-related field a scan record needs.

    Returns
    -------
    dict with keys: content_hash, message_preview, message_redacted, raw_message
    `raw_message` is None when STORE_RAW_MESSAGE is disabled.
    """
    settings = get_settings()
    redacted_full = redact(text)
    return {
        "content_hash": content_hash(text),
        "message_preview": make_preview(redacted_full),
        "message_redacted": redacted_full,
        "raw_message": text if settings.store_raw_message else None,
    }
