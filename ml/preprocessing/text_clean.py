"""
ScamShield AI - ml/preprocessing/text_clean.py
==============================================
The cleaning pipeline used by the MACHINE LEARNING model.

Important design decision
-------------------------
The rule engine uses `normalize.canonicalize()` (aggressive de-obfuscation).
The ML model uses this lighter pipeline instead, because:

  * The model must see text that resembles what it was trained on (real SMS).
  * TF-IDF + linear models already learn that "urgent" and "URGENT!" carry
    similar weight; over-normalising destroys the n-gram structure that makes
    the model good.
  * Keeping the two pipelines separate means a bug in one cannot silently
    change the other's behaviour.

Pipeline
--------
1. lowercase
2. URLs  -> the literal token "<url>"  (structure matters, destination does not)
3. money -> the literal token "<money>"
4. phone numbers -> "<phone>"
5. digits -> "#"  (keeps "win 5000 pounds" as "win # pounds")
6. strip punctuation and non-ASCII noise
7. collapse whitespace

The result is what the TF-IDF vectorizer is fitted on.
"""

from __future__ import annotations

import re
from typing import List

# A compact English stop-word list. Using sklearn's built-in list would pull a
# 300-word file into memory and, more importantly, remove words such as
# "not"/"no"/"won" that carry scam signal. So we curate a SHORT list of words
# with no discriminative value for this task.
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "so", "as",
    "at", "by", "for", "from", "in", "into", "of", "on", "onto", "to", "with",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "them", "their", "this", "that", "these", "those", "there", "here",
    "do", "does", "did", "have", "has", "had", "will", "would", "can", "could",
    "should", "may", "might", "must", "just", "very", "too", "also",
}

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_DISGUISED_URL = re.compile(r"\bh(?:xx|tt)ps?://\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\S+@\S+\.\S+")
_MONEY = re.compile(
    r"(?:rs\.?|inr|usd|\$|£|€|₹)\s?\d[\d,]*(?:\.\d+)?|"
    r"\d[\d,]*(?:\.\d+)?\s?(?:rs|inr|rupees|pounds?|dollars?|euros?|tk)",
    re.IGNORECASE,
)
_PHONE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")
_NUMBERS = re.compile(r"\d+")
_PUNCT = re.compile(r"[^a-z0-9#<>\s]")
_SPACES = re.compile(r"\s+")
# Repeated characters, but only for letters and only 3+ repeats.
_REPEATS = re.compile(r"([a-z])\1{2,}")


def clean_text(
    text: str,
    *,
    remove_stopwords: bool = False,
    collapse_repeats: bool = True,
    keep_placeholders: bool = True,
) -> str:
    """
    Clean one message for the ML vectorizer.

    Parameters
    ----------
    text : str
        Raw message.
    remove_stopwords : bool
        Off by default: stop-word removal hurt recall on this dataset in our
        experiments because short spam ("call now to claim") loses too much.
    collapse_repeats : bool
        "freeeeee" -> "free".
    keep_placeholders : bool
        Keep tokens such as "<url>" and "<money>" so the model can learn
        "message containing a money amount + link" patterns.
    """
    if not isinstance(text, str) or not text.strip():
        return ""

    value = text.lower()

    # Order matters: replace the most specific patterns first.
    value = _DISGUISED_URL.sub(" <url> ", value)
    value = _URL.sub(" <url> ", value)
    value = _EMAIL.sub(" <email> ", value)
    value = _MONEY.sub(" <money> ", value)
    value = _PHONE.sub(" <phone> ", value)
    value = _NUMBERS.sub(" # ", value)

    if collapse_repeats:
        value = _REPEATS.sub(r"\1", value)

    value = _PUNCT.sub(" ", value)
    value = _SPACES.sub(" ", value).strip()

    if not keep_placeholders:
        for token in ("<url>", "<email>", "<money>", "<phone>"):
            value = value.replace(token, " ")

    if remove_stopwords:
        value = " ".join(w for w in value.split() if w not in STOP_WORDS)

    return _SPACES.sub(" ", value).strip()


def clean_batch(texts: List[str], **kwargs) -> List[str]:
    """Vectorised helper: clean a list of messages."""
    return [clean_text(text, **kwargs) for text in texts]


# Feature helpers used by the explanation layer (not by TF-IDF).
def keyword_flags(cleaned: str) -> dict:
    """
    Cheap, interpretable features shown in the UI next to the ML verdict.

    These are NOT fed to the model (TF-IDF is); they exist so the user can see
    which vocabulary pushed the message towards "spam".
    """
    vocab = {
        "money_terms": ("money", "cash", "prize", "win", "claim", "award", "reward"),
        "urgency_terms": ("urgent", "now", "immediately", "expire", "today", "hurry"),
        "contact_terms": ("call", "text", "sms", "reply", "contact", "whatsapp"),
        "credential_terms": ("otp", "pin", "password", "verify", "account", "login"),
        "link_present": ("<url>",),
    }
    tokens = set(cleaned.split())
    return {
        name: sorted(word for word in words if word in tokens)
        for name, words in vocab.items()
    }


if __name__ == "__main__":  # python -m ml.preprocessing.text_clean
    demo = [
        "WINNER!! You have won £2000 cash. Call 09061701461 now to claim!",
        "Rs.1,250.00 debited from A/c XX1234 to VPA rahul@okhdfcbank.",
        "URGENT: verify your account at http://sbi-verify.xyz/login FREE!!!",
    ]
    for message in demo:
        cleaned = clean_text(message)
        print(f"\nin : {message}\nout: {cleaned}")
        print("   flags:", keyword_flags(cleaned))
