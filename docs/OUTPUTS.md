# ScamShield AI — Actual Output

Captured from the **running deployment** at `http://localhost:8000` on 2026-11-09 18:53 UTC.
Every field below is a real HTTP response — nothing is illustrative.

Profile: `ENVIRONMENT=production`, database `sqlite`, model `loaded`, Gemini `not configured`.

```
$ python scripts/prod_smoke_test.py
===================================================================
 ✓ API health            10 ms
 ✓   status              ok
 ✓   database            ok
 ✓   ml_model            ok
 ✓   gemini              not_configured (optional)
 ✓ Model metrics         LogisticRegression F1 0.9407 (3 algorithms compared)
 ✓ Scan scam sample      critical in 7 ms
 ✓   ML active           spam
 ✓   URL flagged         score 67
 ✓ Scan benign control   low
 ✓ Stats endpoint        222 scans
 ✓ UI health             1 ms
===================================================================
 12/12 checks passed
===================================================================
```
---

## 1. Health check

```bash
curl -s <api>/api/v1/health | python3 -m json.tool
```

```json
{
  "status": "ok",
  "app_name": "ScamShield AI",
  "version": "1.0.0",
  "environment": "production",
  "model_available": true,
  "gemini_configured": false,
  "database_backend": "sqlite",
  "timestamp": "2026-11-09T18:53:47.344141Z",
  "components": {
    "api": "ok",
    "database": "ok",
    "ml_model": "ok",
    "gemini": "not_configured"
  }
}
```
---

## 2. Message analysis — English

**Input**

```
Dear Customer, your SBI KYC has been suspended today. Update immediately at http://sbi-kyc-verify.xyz/login or your account will be blocked within 24 hours. - SBI Team
```

**Verdict: CRITICAL · 100/100 · Do not interact with this message** (3 ms)

| Layer | Output |
|---|---|
| Rule engine | 100/100 · 9 rules matched |
| ML model | P(spam)=**0.9168** → `spam` (threshold 0.5) |
| URL analysis | 1 link · 67/100 · imitates `sbi` |
| Explanation | source `fallback` |

**Triggered rules**

| Rule | Severity | Matched text |
|---|---|---|
| `R_KYC_SCAM` | high | …mmediately at http://sbi-kyc-verify.xyz/login or your accoun… |
| `R_LOOKALIKE_DOMAIN` | high | …y. update immediately at http://sbi-kyc-verify.xyz/login or your account wi… |
| `R_THREAT_LANGUAGE` | high | …verify.xyz/login or your account will be blocked within 24 hours. - sbi t… |
| `R_BANK_IMPERSONATION` | medium | dear customer, your sbi kyc has been suspended t… |
| `R_NON_HTTPS_LINK` | medium | …y. update immediately at http://sbi-kyc-verify.xyz/login or your account will be… |
| `R_SUSPICIOUS_TLD` | medium | …y. update immediately at http://sbi-kyc-verify.xyz/login or your account wi… |
| `R_URGENCY_LANGUAGE` | medium | …suspended today. update immediately at http://sbi-kyc-verify… |
| `R_GENERIC_GREETING` | low | dear customer, your sbi kyc has been s… |

**Fusion reasons**

- KYC update / suspension claim (high)
- Domain imitates a known brand (high)
- Threatens loss, blocking or legal action (high)
- Impersonates a bank, wallet or payment app (medium)
- +5 more rule indicator(s) matched
- Statistical model scored this message 92% spam-like (label: spam)
- Link 'sbi-kyc-verify.xyz' scored 67/100 (Domain imitates 'SBI')
- Independent layers agree: ml, rules, url

**Recommended actions**

- Call the organisation back on the official number from its website.
- Complete KYC only inside the bank's official app or at a branch.
- Do not click the link. Preview the domain first.
- Close the message and open the official app or website yourself.
- Do not act out of fear. Verify the claim independently.
- 'sbi-kyc-verify.xyz' imitates SBI. Open the official app instead of the link.
- Do not open the link in this message on any device.

**Explanation** (`fallback`)

> ScamShield's automated checks flagged this message as critical risk (score 100/100). 12 specific warning indicator(s) were found.

---

## 3. Same message — Hindi

**Verdict identical: CRITICAL · 100/100** — only the narrative changes.

```
ScamShield के स्वचालित जाँच में यह संदेश critical जोखिम वाला पाया गया (स्कोर 100/100)। 12 चेतावनी संकेत मिले हैं।

क्या करें:
  • संदेश में दिए किसी भी लिंक पर क्लिक न करें। बैंक का आधिकारिक ऐप खोलें।
  • OTP, PIN, पासवर्ड या कार्ड की जानकारी किसी के साथ साझा न करें।
  • दावे की पुष्टि कार्ड या आधिकारिक वेबसाइट पर दिए नंबर से करें।
```
---

## 4. Hinglish scam — the language-limitation case

**Input**

```
Aapka account band ho jayega. Turant KYC update karein aur OTP batao, warna card block ho jayega. Abhi karein!
```

**Verdict: CRITICAL · 100/100**

| Layer | Output |
|---|---|
| Rule engine | **100/100** · 6 rules |
| ML model | **P(spam)=0.0708** — near zero, because the model is English-only |

```
ScamShield ki automated jaanch me ye message critical risk nikla hai (score 100/100). 6 warning signs mile hain.
```

> The architecture is designed to expose exactly this disagreement: the model is wrong here, the rules are right, and the UI shows both.
---

## 5. URL analysis — never visits the link

**Input** `http://sbi.co.in@secure-login-verify.xyz/kyc/update`

| Property | Value |
|---|---|
| scheme | `http` |
| hostname | `secure-login-verify.xyz` |
| registered_domain | `secure-login-verify.xyz` |
| tld | `xyz` |
| is_https | `False` |
| is_ip_address | `False` |
| is_shortener | `False` |
| subdomain_count | `0` |
| lookalike_of | `None` |
| score | `72` |

**Indicators**

| Code | Severity | Detail |
|---|---|---|
| `userinfo_trick` | critical | Everything before '@' is ignored by browsers, so 'http://sbi.co.in@evil.xyz' actually goes to evil.xyz. |
| `phishing_keywords` | high | The URL contains credential or lure words: kyc, login, secure, update, verify |
| `no_https` | medium | The connection would not be encrypted. Credentials typed on a plain-HTTP page can be intercepted. |
| `suspicious_tld` | medium | '.xyz' is cheap or free to register and is heavily used by phishing campaigns. That alone does not make this URL malicious. |

Verdict: **CRITICAL · 85/100**
---

## 6. Batch analysis

4 messages → `4` results, summary `{"low": 0, "medium": 0, "high": 0, "critical": 4}`

| # | Preview | Risk | Score |
|---|---|---|---|
| 1 | Dear Customer, your SBI KYC has been suspended today. Update… | critical | 100 |
| 2 | Sir I am calling from HDFC bank customer care. Please share … | critical | 100 |
| 3 | I have sent you Rs 5000 by mistake. Please scan this QR code… | critical | 90 |
| 4 | CONGRATULATIONS!!! Your number has won Rs 25,00,000 in the K… | critical | 90 |

---

## 7. Dashboard statistics

```json
{
  "total_scans": 11,
  "spam_detected": 8,
  "suspicious_urls": 1,
  "high_risk_scans": 9,
  "risk_distribution": {
    "low": 1,
    "medium": 1,
    "high": 0,
    "critical": 9
  },
  "average_risk_score": 79.2
}
```

Top indicators: `Impersonates a bank, wallet or payment app` (5), `KYC update / suspension claim` (4), `Threatens loss, blocking or legal action` (4), `Requests a UPI / money transfer` (4), `Domain imitates a known brand` (3), `Link does not use HTTPS` (3)
---

## 8. Model performance (measured)

Dataset: UCI SMS Spam Collection (id 228) · active: **LogisticRegression**

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | Selected |
|---|---|---|---|---|---|---|
| MultinomialNB | 0.9845 | 0.9828 | 0.8906 | 0.9344 | 0.9896 |  |
| LogisticRegression | 0.9855 | 0.9520 | 0.9297 | 0.9407 | 0.9985 | ✅ |
| RandomForest | 0.9864 | 0.9750 | 0.9141 | 0.9435 | 0.9982 |  |

**Selection:** LogisticRegression: spam F1 0.9407, precision 0.9520, recall 0.9297, ROC-AUC 0.9985 on the held-out test set; 5-fold CV F1 0.9372 +/- 0.0116. It is statistically tied on F1 with RandomForest, MultinomialNB (gap < 0.01, smaller than the CV fold spread), so the tie-break was ROC-AUC (0.9985) and then model simplicity.

**Top spam terms:** `phone`, `money`, `txt`, `url`, `text`, `call phone`, `free`, `call`


**Top ham terms:** `my`, `me`, `ok`, `gt`, `lt`, `that`, `can`, `lt gt`

---

## 9. Rule catalogue

`37` rules total.

| Category | Rules |
|---|---|
| link | 7 |
| payment | 5 |
| credential | 3 |
| otp | 2 |
| phishing | 2 |
| impersonation | 2 |
| social_engineering | 2 |
| reward | 2 |
| obfuscation | 2 |
| urgency | 1 |
| threat | 1 |
| kyc | 1 |
| banking | 1 |
| job | 1 |
| investment | 1 |
| malware | 1 |
| language | 1 |
| contact | 1 |
| transactional | 1 |

---

## 10. History (redacted)

| When (UTC) | Type | Risk | Score | ML | Preview |
|---|---|---|---|---|---|
| 2026-11-09 18:53:47 | message | medium | 20 | spam | Rs.1250.00 debited from A/c XX1234 on 09-11-… |
| 2026-11-09 18:53:47 | message | low | 0 | ham | Hi Rahul, are we still meeting at 6 pm near … |
| 2026-11-09 18:53:47 | url | critical | 85 | not_applicable | http://[EMAIL]/kyc/update… |
| 2026-11-09 18:53:47 | message | critical | 100 | ham | Aapka account band ho jayega. Turant KYC upd… |
| 2026-11-09 18:53:47 | message | critical | 100 | spam | Dear user, your KYC is pending. Install this… |

---

## 11. Load test

| Metric | Value |
|---|---|
| Requests | 200 at concurrency 20 |
| Throughput | **270 req/s** |
| p50 | 35.7 ms |
| p95 | **256.5 ms** |
| p99 | 646.5 ms |

---

## 12. Test suite

```
$ pytest
============================= 250 passed in 5.60s ==============================
```

> Regenerate with `python scripts/capture_outputs.py`.
