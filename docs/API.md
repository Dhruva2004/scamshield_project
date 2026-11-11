# ScamShield AI — API Reference

Base URL: `http://localhost:8000`
API prefix: `/api/v1`
Interactive docs: `/docs` (Swagger UI) · `/redoc` (ReDoc) · `/openapi.json`

All requests and responses are JSON. Errors use one consistent envelope:

```json
{
  "error": "validation_error",
  "message": "The message is empty after trimming whitespace.",
  "request_id": "2f6c1c0e-…"
}
```

Every response carries `X-Request-ID` and `X-Process-Time-Ms` headers.

---

## System

### `GET /api/v1/health`

```bash
curl http://localhost:8000/api/v1/health
```

```json
{
  "status": "ok",
  "app_name": "ScamShield AI",
  "version": "1.0.0",
  "environment": "development",
  "model_available": true,
  "gemini_configured": false,
  "database_backend": "sqlite",
  "timestamp": "2026-11-09T17:16:55Z",
  "components": {
    "api": "ok",
    "database": "ok",
    "ml_model": "ok",
    "gemini": "not_configured"
  }
}
```

---

## Scanning

### `POST /api/v1/scan/message`

Full three-layer analysis. `scan_type: "auto"` detects a bare URL and treats anything else
as a message (embedded links are still analysed).

**Request**

```json
{
  "text": "Dear Customer, your SBI KYC is suspended. Update at http://sbi-kyc-verify.xyz/login within 24 hours.",
  "scan_type": "auto",
  "language": "en",
  "include_explanation": true
}
```

| Field | Type | Rules |
|---|---|---|
| `text` | string | 1–10,000 chars, not blank, not repeated characters |
| `scan_type` | enum | `auto` \| `message` \| `email` \| `url` |
| `language` | enum | `en` \| `hi` \| `hinglish` |
| `include_explanation` | bool | skip Gemini to save quota/latency |

**Response (abbreviated)**

```json
{
  "scan_id": "4e389feaf2294df9b478bab914af86d4",
  "created_at": "2026-11-09T17:09:41Z",
  "scan_type": "message",
  "language": "en",
  "input_preview": "Dear Customer, your SBI KYC is suspended…",
  "rule_engine": {
    "score": 100,
    "risk_level": "critical",
    "matched_count": 9,
    "categories": ["banking", "impersonation", "kyc", "link", "obfuscation", "threat", "urgency"],
    "findings": [
      {
        "rule_id": "R_KYC_SCAM",
        "title": "KYC update / suspension claim",
        "category": "kyc",
        "severity": "high",
        "weight": 20,
        "description": "The 'your KYC is expiring, update now' message is India's most-reported SMS fraud…",
        "matched_text": ["…immediately at http://sbi-kyc-verify.xyz/login or your accoun…"]
      }
    ]
  },
  "ml_prediction": {
    "available": true,
    "label": "spam",
    "spam_probability": 0.9168,
    "threshold": 0.5,
    "confidence": 0.8336,
    "model": {"name": "LogisticRegression", "version": "1.0.0", "available": true},
    "note": "This is the model's estimated spam score, not a guarantee that the message is fraudulent (or safe)…"
  },
  "urls": {
    "urls_found": 1,
    "highest_score": 67,
    "analyses": [
      {
        "raw": "http://sbi-kyc-verify.xyz/login",
        "hostname": "sbi-kyc-verify.xyz",
        "registered_domain": "sbi-kyc-verify.xyz",
        "tld": "xyz",
        "is_https": false,
        "is_ip_address": false,
        "is_shortener": false,
        "subdomain_count": 0,
        "lookalike_of": "sbi",
        "score": 67,
        "indicators": [
          {"code": "brand_lookalike", "label": "Domain imitates 'SBI'", "severity": "high",
           "detail": "The host contains the brand name 'sbi' but is registered as 'sbi-kyc-verify.xyz'…"}
        ]
      }
    ]
  },
  "risk": {
    "level": "critical",
    "score": 100,
    "rule_score": 100,
    "ml_score": 0.9168,
    "headline": "Do not interact with this message",
    "reasons": [
      "KYC update / suspension claim (high)",
      "Domain imitates a known brand (high)",
      "Statistical model scored this message 92% spam-like (label: spam)",
      "Link 'sbi-kyc-verify.xyz' scored 67/100 (Domain imitates 'SBI')",
      "Independent layers agree: ml, rules, url"
    ],
    "recommended_actions": [
      "Never share the OTP. Your bank will never ask for it.",
      "Complete KYC only inside the bank's official app or at a branch.",
      "Do not open the link in this message on any device."
    ]
  },
  "explanation": {
    "available": true,
    "source": "fallback",
    "language": "en",
    "summary": "ScamShield's automated checks flagged this message as critical risk (score 100/100). 12 specific warning indicator(s) were found.",
    "suspicious_elements": ["KYC update / suspension claim", "Domain imitates a known brand"],
    "scam_techniques": ["fake KYC-compliance pressure", "artificial urgency to stop you thinking"],
    "recommendations": ["Do not click any link in this message. Open the official app instead."],
    "disclaimer": "Automated explanation (Gemini unavailable). This is guidance, not proof.",
    "error": "GEMINI_API_KEY is not set."
  },
  "processing_ms": 869,
  "disclaimer": "ScamShield AI provides heuristic and statistical guidance only…"
}
```

### `POST /api/v1/scan/url`

Same schema. The ML classifier is **intentionally skipped** and reports
`ml_prediction.available = false` with the note: *"The ML classifier was trained on SMS
text, so it is not applied to bare URLs."*

```bash
curl -X POST http://localhost:8000/api/v1/scan/url \
  -H "Content-Type: application/json" \
  -d '{"text":"http://sbi.co.in@secure-login-verify.xyz/kyc/update"}'
```

### `POST /api/v1/scan/batch`

Max 20 items. A failing item never aborts the batch.

```json
{
  "items": [
    {"text": "Your KYC is suspended, update at http://sbi-kyc.xyz"},
    {"text": "Hi, see you at 6 pm"}
  ]
}
```

```json
{
  "results": [ /* ScanResponse objects */ ],
  "total": 2,
  "summary": {"low": 1, "medium": 0, "high": 0, "critical": 1}
}
```

### `GET /api/v1/scan/rules`

The complete rule catalogue — exposed on purpose so the heuristics can be audited.

### `GET /api/v1/scan/explain-scoring`

```json
{
  "rule_weights": {"info": 0, "low": 6, "medium": 12, "high": 20, "critical": 32},
  "rule_score_range": "0-100 (capped)",
  "fusion": "final = max(rule_score, ML_component, URL_component) + agreement_bonus…",
  "thresholds": {"low": "0-19", "medium": "20-44", "high": "45-69", "critical": "70-100"}
}
```

---

## History

| Method | Endpoint | Notes |
|---|---|---|
| `GET` | `/api/v1/history` | `page`, `page_size` (≤100), `risk_level`, `scan_type`, `search` |
| `GET` | `/api/v1/history/stats` | Dashboard aggregates + real model metrics |
| `GET` | `/api/v1/history/{scan_id}` | Detail; raw text only with `?include_raw=true` **and** `STORE_RAW_MESSAGE=true` |
| `GET` | `/api/v1/history/export.csv` | Newest 1,000 scans, streamed |
| `DELETE` | `/api/v1/history/{scan_id}` | Delete one |
| `DELETE` | `/api/v1/history` | Clear all (irreversible) |

```bash
curl "http://localhost:8000/api/v1/history?page=1&page_size=10&risk_level=critical"
```

```json
{
  "items": [
    {
      "id": 12,
      "scan_id": "4e389feaf2294df9b478bab914af86d4",
      "created_at": "2026-11-09T17:09:41Z",
      "scan_type": "message",
      "language": "en",
      "risk_level": "critical",
      "risk_score": 100,
      "rule_score": 100,
      "ml_label": "spam",
      "ml_spam_probability": 0.9168,
      "message_preview": "Dear Customer, your SBI KYC is suspended…",
      "indicators": ["KYC update / suspension claim", "Domain imitates 'SBI'"],
      "summary": "Do not interact with this message"
    }
  ],
  "total": 11,
  "page": 1,
  "page_size": 10,
  "has_more": true
}
```

> `message_preview` is **always redacted**. `raw_message` is absent from the list endpoint
> and null on the detail endpoint unless explicitly requested.

---

## Models

### `GET /api/v1/models/comparison`

```json
{
  "available": true,
  "dataset": "UCI SMS Spam Collection (id 228)",
  "vectorizer": "TF-IDF (1-2 grams, min_df=2, max_df=0.9, sublinear_tf)",
  "trained_at": "2026-11-09T17:09:41+00:00",
  "active_model": "LogisticRegression",
  "entries": [
    {"model_name": "MultinomialNB", "accuracy": 0.9845, "precision": 0.9828,
     "recall": 0.8906, "f1": 0.9344, "roc_auc": 0.9896, "train_seconds": 0.0, "chosen": false},
    {"model_name": "LogisticRegression", "accuracy": 0.9855, "precision": 0.952,
     "recall": 0.9297, "f1": 0.9407, "roc_auc": 0.9985, "train_seconds": 0.01, "chosen": true},
    {"model_name": "RandomForest", "accuracy": 0.9864, "precision": 0.975,
     "recall": 0.9141, "f1": 0.9435, "roc_auc": 0.9982, "train_seconds": 1.4, "chosen": false}
  ],
  "selection_reason": "LogisticRegression: spam F1 0.9407 … statistically tied on F1 with RandomForest, MultinomialNB (gap < 0.01 …), so the tie-break was ROC-AUC (0.9985) and then model simplicity."
}
```

### `GET /api/v1/models/info`

Metadata of the active artefact, including its recorded `limitations` array (English-only,
minority class, probability disclaimer).

### `GET /api/v1/models/terms?top_k=25`

Per-term coefficients of the linear model — the interpretability payoff of choosing
Logistic Regression.

```json
{
  "available": true,
  "model": "LogisticRegression",
  "top_spam_terms": [{"term": "claim", "weight": 4.87}, {"term": "txt", "weight": 4.31}],
  "top_ham_terms": [{"term": "lt", "weight": -3.92}, {"term": "ok", "weight": -3.55}],
  "note": "Weights are log-odds contributions from TF-IDF features…"
}
```

---

## Samples

### `GET /api/v1/samples`

The 11 curated demo messages used by the UI's "try an example" buttons, each with its
`expected_risk` and, where relevant, a `note` explaining an ambiguity.

---

## Authentication

Optional. If `API_KEY` is set in `.env`, `/scan/*` and `/history/*` require:

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/api/v1/history
```

Missing or wrong key → `401` with the standard error envelope.

---

## Status codes

| Code | Meaning |
|---|---|
| `200` | OK |
| `401` | Missing/invalid `X-API-Key` |
| `404` | Unknown `scan_id` |
| `422` | Validation failure (with per-field `details`) |
| `500` | Unexpected error (message only — no traceback) |
| `502` | Upstream AI failure that could not be degraded |
| `503` | Model or database unavailable |
