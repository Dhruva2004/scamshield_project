"""
ScamShield AI - frontend/views/about_page.py
============================================
Project documentation rendered inside the app.

Judges and examiners usually ask "what are the limitations?" before "what does
it do?". This page answers both, including the parts that do not work well.
"""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.components import ui


def render() -> None:
    st.subheader("About ScamShield AI")

    st.markdown(
        """
ScamShield AI analyses suspicious digital communication — SMS, WhatsApp messages,
emails, social-media DMs and links — and explains *why* something looks like a scam.

It was built as an MSc Computer Science project and a Samsung Innovation Campus
demonstration. The design target was not "a model that scores well on a dataset"
but "a system a non-technical person can trust, audit and learn from".
"""
    )

    st.markdown("### How it works")
    st.markdown(
        """
```
 message / URL
      │
      ├─► Rule engine        deterministic, explainable, 40+ rules
      ├─► ML classifier      TF-IDF + Logistic Regression (trained on UCI SMS Spam)
      ├─► URL analyser       static pattern checks, never visits the link
      │
      ├─► Risk fusion        max(components) + agreement bonus → LOW…CRITICAL
      ├─► Gemini explainer   plain-language guidance in EN / HI / Hinglish
      └─► SQLite             redacted history + dashboard statistics
```

The three detection layers are always reported **separately**. A user can see the
rule score, the model probability and the URL score individually, which is what
makes the verdict auditable.
"""
    )

    st.markdown("### Technology")
    st.markdown(
        """
| Layer | Stack |
|---|---|
| Backend | Python 3.10+, FastAPI, Pydantic v2, Uvicorn, SQLite |
| Machine learning | scikit-learn, pandas, NumPy, TF-IDF, Joblib |
| Generative AI | Google Gemini (`google-genai`), optional with graceful fallback |
| Frontend | Streamlit + custom HTML/CSS/Altair |
| Testing | Pytest — 200+ automated tests |
"""
    )

    st.markdown("### Language support — the honest version")
    st.markdown(
        """
| Layer | English | Hindi | Hinglish |
|---|---|---|---|
| **ML classifier** | ✅ trained on it | ❌ not trained | ❌ not trained |
| **Rule engine** | ✅ full rule set | ⚠️ curated keyword list | ⚠️ curated keyword list |
| **Explanation (Gemini)** | ✅ | ✅ | ✅ |

The classifier was trained on the UCI SMS Spam Collection, which is English-only.
Presenting its output as reliable for Hindi or Hinglish would be misleading. In
practice, Hinglish scams are caught by the curated rules — the ML score is simply
near-zero for them, and the UI shows both facts side by side.

A multilingual training pipeline (IndicNLP / AI4Bharat corpora, transliteration
normalisation, per-language models) is designed in `docs/future_scope.md`.
"""
    )

    st.markdown("### Known limitations")
    st.markdown(
        """
1. **The ML model is a 2005-era English SMS model.** It over-scores genuine Indian
   bank debit alerts (documented false positive: a real SBI alert scores ~20/100 MEDIUM).
2. **Rules are finite.** A scam phrased in a way no rule anticipates can pass.
3. **URL analysis is pattern-based only.** It never fetches the page, so it cannot
   detect a legitimate domain hosting a phishing kit.
4. **Gemini explains, it does not detect.** If it is unavailable the deterministic
   fallback is used and the app keeps working.
5. **Deliberately left as MEDIUM:** we did not tune thresholds until every test
   looked perfect. The false positive is documented, not hidden.
"""
    )

    st.markdown("### Privacy")
    st.markdown(
        """
* Phone numbers, emails, card numbers, OTP values, UPI IDs and IFSC codes are
  redacted before storage **and** before any text is sent to Gemini.
* Only a salted SHA-256 hash plus a redacted preview is retained by default.
* History can be cleared by the user at any time (`STORE_RAW_MESSAGE=false`
  disables plaintext storage entirely).
* The URL analyser never contacts the domains you submit.
"""
    )

    ui.disclaimer_box()

    st.markdown("### Live configuration")
    try:
        health = api_client.health()
        st.json(health)
    except api_client.APIError as exc:
        st.warning(f"API not reachable: {exc}")
