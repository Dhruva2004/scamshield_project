# ScamShield AI — Limitations

This document exists because a security tool that hides its weaknesses is dangerous.
Every limitation below was observed during development, not copied from a template.

---

## 1. The ML model is English-only

**Observed:** a Hinglish scam — *"Aapka account band ho jayega. Turant KYC update karein
aur OTP batao"* — scores **P(spam) = 0.07** from the classifier while the rule engine
scores **100/100**.

The UCI SMS Spam Collection is entirely English. Presenting the classifier as
multilingual would be false. The UI therefore shows both numbers side by side; the
disagreement is the point.

| Layer | English | Hindi | Hinglish |
|---|---|---|---|
| ML classifier | trained | not trained | not trained |
| Rule engine | full set | curated keywords | curated keywords |
| Explanation | ✅ | ✅ | ✅ |

*Mitigation:* the Hinglish/Hindi signal comes from `R_HINDI_HINGLISH_SIGNALS` and
language-specific patterns inside each rule. This is a keyword list, not a model — it has
the recall of a keyword list, no more.

*Fix:* multilingual training pipeline in [FUTURE_SCOPE.md](FUTURE_SCOPE.md#1-multilingual-training-pipeline).

---

## 2. Documented false positive on genuine bank alerts

**Observed:** the real SBI alert

> *Rs.1250.00 debited from A/c XX1234 on 09-11-26 to VPA rahul@okhdfcbank. Balance
> 12000.00. Not you? Call the number on your card. -SBI*

originally scored **CRITICAL**. Cause: the 2005-era corpus barely contains transactional
alerts, so the model returns P(spam) = 0.82 for them. Accuracy on this input is poor *even
though test accuracy is 98.55%* — a clean illustration of distribution shift.

**What we did (and did not do):**

1. Added `R_TRANSACTIONAL_ALERT_STRUCTURE` — a structural rule with **weight 0** that
   recognises the amount + debit/credit + masked-account + balance shape.
2. When that structure matches **and no high/critical rule fires**, the ML component is
   multiplied by `TRANSACTIONAL_ML_DAMPING = 0.25` and the rule score is capped at 15.
3. Result: **MEDIUM, 20/100** (was CRITICAL 100).
4. We did **not** tune further. The sample's `expected_risk` is the honest `"medium"` and
   it carries a `note` explaining the false positive.

**Why this cannot be exploited:** the damping only applies when *zero* high/critical
severity rules fire. A scammer who copies the transaction format still trips the link, KYC,
OTP, threat and payment rules.

---

## 3. Rules are finite and can be out-phrased

The 40+ rules are regex heuristics. A scam written in a way no rule anticipates — a novel
metaphor, a new payment rail, a dialect we did not enumerate — can pass with a low score.

We reduce, not eliminate, this risk by: matching on de-obfuscated text (defeats `K.Y.C`,
`acc0unt`, `hxxp`), combining rules that are dangerous together (`COMBINATIONS`), and
flagging obfuscation itself as a signal.

**A low score means "no known pattern matched", never "this is safe."**

---

## 4. URL analysis never touches the network

`url_analyzer.py` performs **no DNS lookup, no HTTP request, no TLS inspection**. Verified
by `tests/test_phase5_url.py::TestSafety::test_never_makes_network_calls`, which patches
`socket.connect` and asserts zero calls.

Consequences:

| Cannot detect | Example |
|---|---|
| Whether a site currently serves malware | a clean-looking domain delivering a payload |
| A compromised legitimate site | phishing hosted on a hacked WordPress site |
| Live certificate problems | an expired or mismatched certificate |
| Reputation | a domain blacklisted 10 minutes ago |
| Redirect chains | a shortener pointing to a phishing page |

**A low URL score is not a safety verdict.**

---

## 5. Gemini explains, it does not detect

The verdict is produced entirely by the rule engine, the ML model and the URL analyser —
all deterministic and testable. Gemini receives the verdict and rewrites it in plain
language. It cannot add findings (the system prompt forbids inventing indicators) and it
never claims certainty about intent.

Therefore:

* Disabling Gemini changes **no** risk score. Only the narrative.
* A Gemini outage degrades wording, never detection.
* Gemini output is not evaluated by automated tests (non-deterministic); we test the
  fallback path, the prompt construction, the JSON parser and every failure branch.

---

## 6. The risk score is a heuristic, not a probability

`risk.score` is computed as `max(rule_score, ML_component, URL_component)` plus agreement
bonuses, with documented thresholds (LOW 0–19, MEDIUM 20–44, HIGH 45–69, CRITICAL 70–100).
It is **not calibrated**: "78/100" does not mean "78% chance of fraud".

Likewise `ml_prediction.spam_probability` is the model's score for the *spam* class as
defined by the training data — not the probability that this specific message is criminal.

Both disclaimers are present in every API response and every UI result.

---

## 7. Class imbalance narrows what the metrics mean

Spam is 12.4% of the dataset. We report precision/recall/F1 rather than accuracy alone, but
even F1 = 0.9407 is measured on 2005-era SMS English, not on modern Indian UPI/KYC
phishing. The real-world performance on the traffic this app targets is **unknown and
probably lower**. A proper evaluation needs a labelled corpus of current Indian scam
messages, which does not publicly exist in adequate quantity.

---

## 8. SQLite and single-process assumptions

* SQLite allows one writer at a time. Fine for a demo and a small deployment; a class of
  50 concurrent students would benefit from PostgreSQL (`DATABASE_URL` is already
  swappable, and all SQL is confined to `repositories.py`).
* The `ModelRegistry` caches one model per process. With multiple workers, each loads its
  own copy (fine — the artefact is 162 KB).
* No rate limiting is implemented. Add `slowapi` or a reverse proxy before exposing the API.

---

## 9. Not a substitute for official verification

ScamShield AI is decision support for an individual. It cannot see your actual account
state, cannot verify a caller's identity, and cannot recover money. The final advice in
every response is always the same: verify through the official channel, and report fraud at
**cybercrime.gov.in** or **1930** (India).

---

## Summary table

| Claim | Status | Evidence |
|---|---|---|
| Detects common Indian scam patterns | ✅ works | 246 tests; 11 golden demo samples |
| Explains why, auditably | ✅ works | `/scan/rules`, matched text in every finding |
| Works without Gemini | ✅ works | fallback tested in 3 languages |
| Works without a trained model | ✅ works | `available=false` path tested |
| Never visits submitted URLs | ✅ works | `socket.connect` monkeypatch test |
| Reliable for Hindi/Hinglish **ML** | ❌ does not | P(spam)=0.07 on a Hinglish scam |
| No false positives | ❌ does not | documented MEDIUM on a genuine bank alert |
| Probability of fraud | ❌ not calibrated | heuristic thresholds, stated everywhere |
