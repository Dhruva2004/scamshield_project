# 🛡️ ScamShield AI

**AI-powered detection and explanation of scam, spam and phishing messages.**

An MSc Computer Science / Samsung Innovation Campus project that combines an explainable
rule engine, a supervised machine-learning classifier and Google Gemini explanations behind
a professional cybersecurity dashboard — with every limitation stated honestly.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32%2B-FF4B4B?logo=streamlit&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-1.4%2B-F7931E?logo=scikitlearn&logoColor=white)
![Tests](https://img.shields.io/badge/tests-250%20passing-22c55e)
![Coverage](https://img.shields.io/badge/coverage-79%25-4f8cff)

---

## Table of contents

1. [What it does](#what-it-does)
2. [Measured results (not invented)](#measured-results-not-invented)
3. [Architecture](#architecture)
4. [Project structure](#project-structure)
5. [Installation (Windows + macOS/Linux)](#installation)
6. [Running the application](#running-the-application)
7. [Deployment](#deployment)
8. [Configuration](#configuration)
9. [API reference](#api-reference)
10. [Testing](#testing)
11. [Honest limitations](#honest-limitations)
12. [Security & privacy](#security--privacy)
13. [Documentation index](#documentation-index)
14. [Roadmap](#roadmap)

---

## What it does

Paste an SMS, WhatsApp message, email, DM or URL and ScamShield AI returns:

| Output | Description |
|---|---|
| **Risk level** | LOW · MEDIUM · HIGH · CRITICAL with a 0–100 score |
| **Rule findings** | Every triggered rule, the exact text that matched, and why it matters |
| **ML prediction** | Spam probability from a TF-IDF + Logistic Regression model, with its own disclaimer |
| **URL analysis** | 15+ static checks per link (never visits the link) |
| **Explanation** | Plain-language guidance in **English, Hindi and Hinglish** |
| **Recommended actions** | Concrete next steps, ending with cybercrime.gov.in / 1930 |
| **History & dashboard** | Redacted SQLite history, statistics, model performance |

### Detection coverage

KYC/bank impersonation · OTP & credential theft · UPI/collect-request scams · lottery &
prize lures · fake job offers · investment fraud · "digital arrest" & authority
impersonation · malicious APK/remote-access pushes · shortened and look-alike domains ·
Hinglish scam phrasing.

---

## Measured results (not invented)

Every number below comes from an actual run of `python scripts/train_models.py` on the
**UCI SMS Spam Collection** (5,572 raw rows → **5,158 after duplicate removal**,
4,516 ham / 642 spam, 80/20 stratified split, `random_state=42`).

| Model | Accuracy | Precision (spam) | Recall (spam) | F1 | ROC-AUC | Train time | Selected |
|---|---|---|---|---|---|---|---|
| MultinomialNB | 0.9845 | 0.9828 | 0.8906 | 0.9344 | 0.9896 | 0.00 s | |
| **LogisticRegression** | **0.9855** | **0.9520** | **0.9297** | **0.9407** | **0.9985** | **0.01 s** | ✅ |
| RandomForest | 0.9864 | 0.9750 | 0.9141 | 0.9435 | 0.9982 | 1.40 s | |

**Confusion matrix (selected model):**

|  | pred ham | pred spam |
|---|---|---|
| **actual ham** | 898 | 6 |
| **actual spam** | 9 | 119 |

**Why Logistic Regression, when Random Forest has a marginally higher F1?**

The F1 gap (0.9435 vs 0.9407) is **0.0028** — far smaller than the cross-validation fold
spread (±0.0116 to ±0.0167). Reporting that as a "win" would be dishonest. The selection
rule was declared up front:

> Models within `F1_TIE_TOLERANCE = 0.01` are statistically tied → break the tie on
> **ROC-AUC** (LR: 0.9985 vs RF: 0.9982) → then on **simplicity**.

Logistic Regression wins on substance: **162 KB vs 3.3 MB**, microsecond inference, better
calibrated probabilities, and *per-token coefficients* — which the app exposes through
`/api/v1/models/terms` and uses to show which words pushed a message towards spam. For a
project whose entire point is explainability, that is decisive.

**Why F1 and recall rather than accuracy?** The dataset is only 12.4% spam. A model that
always answers "ham" scores 87.6% accuracy and catches zero scams.

📄 Full report: [`ml/evaluation/reports/evaluation_report.md`](ml/evaluation/reports/evaluation_report.md) ·
![confusion matrix](ml/evaluation/reports/confusion_matrix.png)

---

## Architecture

![architecture](docs/diagrams/architecture.svg)

Three independent layers, fused into one verdict, each **always reported separately** so a
user can audit the reasoning:

```
message
  ├─► Rule engine        deterministic · 40+ rules · fully explainable
  ├─► ML classifier      TF-IDF + LogisticRegression · statistical
  ├─► URL analyser       15+ static patterns · never makes a network call
  │
  ├─► Risk fusion        max(layers) + agreement bonus → LOW…CRITICAL
  ├─► Gemini explainer   EN / HI / Hinglish · explains, never detects
  └─► SQLite             redacted history + dashboard statistics
```

**Graceful degradation is a hard requirement, not an afterthought:**

| Missing component | Behaviour |
|---|---|
| ML model not trained | `ml_prediction.available=false`, scan still succeeds on rules + URLs |
| No `GEMINI_API_KEY` | Deterministic fallback explanation (all 3 languages) |
| Gemini outage / quota | Fallback explanation, error reason surfaced in the UI |
| Database write fails | Scan still returned; failure logged only |

---

## Project structure

```
ScamShield-AI/
├── backend/                      # FastAPI application
│   ├── main.py                   # app factory, middleware, lifespan, router wiring
│   ├── config.py                 # pydantic-settings: the ONLY place env vars are read
│   ├── api/                      # HTTP layer — thin routers, no business logic
│   │   ├── dependencies.py       # optional X-API-Key guard
│   │   ├── health.py             # /health, / (landing)
│   │   ├── scan.py               # /scan/message | /scan/url | /scan/batch | /scan/rules
│   │   ├── history.py            # /history (+ /stats, /export.csv, DELETE)
│   │   ├── models.py             # /models/comparison | /models/info | /models/terms
│   │   └── samples.py            # curated demo inputs served to the UI
│   ├── core/
│   │   ├── logging_config.py     # one log format for the whole app
│   │   └── exceptions.py         # domain errors → structured JSON, no stack traces
│   ├── schemas/                  # Pydantic v2 contracts (the API "shape")
│   │   ├── common.py             # RiskLevel, ScanType, Language, Severity (+weights)
│   │   ├── scan.py               # ScanRequest/Response and every sub-result
│   │   ├── history.py            # HistoryItem/Detail/Page, StatsResponse, Health
│   │   └── evaluation.py         # ModelPerformance, ModelComparison
│   ├── services/                 # ALL business logic lives here
│   │   ├── scan_service.py       # orchestrator: privacy→rules→ML→URL→risk→explain→save
│   │   ├── rule_catalog.py       # 40+ rules as declarative data (the analyst's file)
│   │   ├── rule_engine.py        # matching + category de-duplication + severity floor
│   │   ├── url_analyzer.py       # static URL checks with an explicit no-network contract
│   │   ├── risk_assessor.py      # fusion policy + reason/action generation
│   │   ├── gemini_service.py     # Gemini + deterministic fallback + prompt redaction
│   │   ├── model_registry.py     # lazy artefact loading, never fatal
│   │   └── privacy.py            # redaction, salted hashing, retention payloads
│   ├── database/
│   │   ├── connection.py         # schema DDL, PRAGMAs, context-managed connections
│   │   └── repositories.py       # the only module that writes SQL
│   └── models/                   # reserved for future ORM models (PostgreSQL profile)
│
├── frontend/                     # Streamlit UI
│   ├── app.py                    # page config, sidebar, routing
│   ├── api_client.py             # the ONLY module that speaks HTTP
│   ├── components/
│   │   ├── ui.py                 # HTML/CSS blocks (metric cards, pills, meters)
│   │   ├── charts.py             # Altair builders (donut, trend, comparison)
│   │   └── result_view.py        # renders one scan, keeping layers visibly separate
│   ├── views/                    # dashboard, analyser, url_page, history, statistics, about
│   ├── styles/theme.css          # custom dark cybersecurity theme
│   └── locales/                  # reserved for future i18n message catalogues
│
├── ml/
│   ├── data/
│   │   ├── download_dataset.py   # reproducible UCI download + cleaning
│   │   ├── raw/                  # downloaded archive (git-ignored)
│   │   └── processed/            # sms_spam.csv (git-ignored, regenerable)
│   ├── preprocessing/
│   │   ├── normalize.py          # de-obfuscation for the RULE engine
│   │   └── text_clean.py         # lighter cleaning for the ML model
│   ├── training/train.py         # 3 algorithms, stratified CV, real metrics, persistence
│   ├── evaluation/
│   │   ├── evaluate.py           # re-scores the artefact, writes the report + PNG
│   │   └── reports/              # evaluation_report.md/.json/confusion_matrix.png
│   ├── inference/predictor.py    # MLPrediction + per-token explanations
│   └── vectorizers/              # tfidf_vectorizer.joblib (git-ignored)
│
├── models/                       # model_*.joblib + metrics.json (git-ignored)
├── tests/                        # 250 tests across 8 files (see Testing)
├── docs/
│   ├── diagrams/                 # architecture, DFD, use case, UML
│   ├── OUTPUTS.md                # captured live responses (regenerable)
│   ├── PROJECT_REPORT.md         # full academic report
│   ├── INSTALLATION.md           # Windows-first step-by-step guide
│   ├── API.md                    # endpoint reference with curl examples
│   ├── DEMO_SCRIPT.md            # 8-minute presentation walkthrough
│   ├── FUTURE_SCOPE.md           # multilingual pipeline, reputation APIs, React
│   └── LIMITATIONS.md            # what does *not* work, and why
├── scripts/
│   ├── train_models.py           # one-command training
│   ├── seed_demo_data.py         # populate the dashboard via the real pipeline
│   ├── run_dev.py                # start backend + frontend together, supervised
│   ├── prod_smoke_test.py        # post-deploy verification, exit code 0/1
│   ├── export_for_git.py         # Git-ready export (force-includes the model)
│   └── capture_outputs.py        # regenerate docs/OUTPUTS.md from a live API
├── deploy/
│   ├── Dockerfile.api            # multi-stage, non-root, healthcheck, 2 workers
│   ├── Dockerfile.ui             # Streamlit image
│   ├── docker-compose.yml        # api + ui + optional postgres profile
│   ├── nginx.conf                # TLS, rate limits, Streamlit WebSocket upgrade
│   ├── scamshield-api.service    # systemd unit (hardened)
│   ├── scamshield-ui.service     # systemd unit (hardened)
│   └── README.md                 # the three deployment paths + env var reference
├── docs/OUTPUTS.md               # real captured output of the running deployment
├── VERIFY.md                     # every command run, with its actual output
├── data/                         # SQLite database + CSV exports (git-ignored)
├── requirements.txt
├── .env.example
└── .gitignore
```

### Why this structure?

* **`api/` vs `services/`** — routers only do HTTP; business logic is testable without a
  client. This is what makes the 250 tests fast (~5 s total).
* **`rule_catalog.py` separate from `rule_engine.py`** — data vs logic. A security analyst
  adds a rule without touching the scoring algorithm.
* **Two preprocessing modules** — `normalize.py` de-obfuscates for pattern matching;
  `text_clean.py` keeps the text natural for TF-IDF. Different jobs, different files.
* **`api_client.py` as the only HTTP boundary** — swapping Streamlit for React changes one
  layer, not the application.

---

## Installation

Full step-by-step guide with Windows-specific commands:
**[docs/INSTALLATION.md](docs/INSTALLATION.md)**

### Quick start (Windows PowerShell)

```powershell
# 1. Go to the project
cd ScamShield-AI

# 2. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# If blocked by execution policy:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Create your environment file
Copy-Item .env.example .env
#    then edit .env and set GEMINI_API_KEY (optional but recommended)

# 5. Download and prepare the dataset
python -m ml.data.download_dataset

# 6. Train the model (writes models/ + metrics.json)
python scripts/train_models.py

# 7. Evaluate and write the report artefacts
python -m ml.evaluation.evaluate

# 8. Run the tests
pytest -q
```

### Quick start (macOS / Linux)

```bash
cd ScamShield-AI
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env      # then edit GEMINI_API_KEY
python -m ml.data.download_dataset
python scripts/train_models.py
python -m ml.evaluation.evaluate
pytest -q
```

---

## Running the application

### Option A — both services with one command (recommended for demos)

```powershell
python scripts/run_dev.py
```

* Dashboard → <http://localhost:8501>
* API docs → <http://localhost:8000/docs>

### Option B — two terminals

**Terminal 1 — backend**
```powershell
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — frontend**
```powershell
streamlit run frontend/app.py
```

> Windows note: if `uvicorn` or `streamlit` is "not recognised", use
> `python -m uvicorn …` and `python -m streamlit …`, or run
> `pip install -r requirements.txt` again inside the activated virtual environment.

### Populate the dashboard for a presentation

```powershell
python scripts/seed_demo_data.py --clear
```

This runs the **real pipeline** over the 11 curated samples, so every score on screen was
genuinely computed.

---

## Deployment

Full instructions, including PostgreSQL, TLS and PaaS: **[deploy/README.md](deploy/README.md)**.
**Start here — complete 9-step runbook, start to finish:
[docs/START_HERE_DEPLOY.md](docs/START_HERE_DEPLOY.md)** (prerequisites → GitHub →
Render → Streamlit → verification, with a "you should see" check at every step).

Reference material: [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) (troubleshooting),
[docs/PUSH_VERIFY.md](docs/PUSH_VERIFY.md) (prove a push worked).

### 0. Free cloud (Render + Streamlit Cloud)

```bash
python scripts/export_for_git.py     # Git-ready folder; force-includes the .joblib model
cd dist/git-export && git init && git add -A && git commit -m "Deploy ScamShield AI"
# push to GitHub, then Render -> New -> Blueprint -> pick the repo (reads render.yaml)
```

`render.yaml` is included: Docker build, 2 workers, `STORE_RAW_MESSAGE=false`,
generated salt, health check on `/api/v1/health`, and first-boot demo seeding
(`SEED_DEMO_DATA=true`) so a fresh deploy is not an empty dashboard.

### 1. Docker Compose (recommended)

```bash
docker compose -f deploy/docker-compose.yml up -d --build
python scripts/prod_smoke_test.py --api http://localhost:8000 --ui http://localhost:8501
```

Ships an `api` container (multi-stage, non-root uid 1001, 2 uvicorn workers, healthcheck,
model warmed at startup), a `ui` container, and a named volume `scamshield-data` so scan
history survives rebuilds. `--profile postgres` switches to PostgreSQL.

### 2. systemd + nginx (Linux VM)

```bash
sudo cp deploy/scamshield-api.service deploy/scamshield-ui.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now scamshield-api scamshield-ui
sudo cp deploy/nginx.conf /etc/nginx/sites-available/scamshield   # TLS, rate limits, WebSocket
```

`deploy/nginx.conf` includes the WebSocket upgrade map Streamlit needs (without it the
dashboard hangs on "Please wait…") and `30r/m` per-IP limiting on `/api/v1/scan/`.

### 3. Production profile without any infra

The same code path the containers use — no reload, multiple workers, proxy headers honoured:

```bash
# Linux / macOS
ENVIRONMENT=production DEBUG=false WEB_CONCURRENCY=2 \
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 \
  --workers 2 --proxy-headers --forwarded-allow-ips='*'

# Windows PowerShell
$env:ENVIRONMENT="production"; $env:DEBUG="false"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers
```

### Always verify after deploying

```bash
python scripts/prod_smoke_test.py --api https://api.example.com --ui https://app.example.com --api-key "$API_KEY"
```

12 checks (health, DB, model, Gemini status, measured F1, a known scam must score
`critical`, a benign control must score `low`, stats, UI reachability); exit code **0**
on success, **1** on failure — safe to use as a deploy hook.

Measured on the production profile in this repository: **12/12 checks**, scam sample
classified `critical` in **20 ms**, and **302 req/s** at concurrency 20 (p50 39 ms,
p95 172 ms, 0 errors). See [docs/OUTPUTS.md](docs/OUTPUTS.md) for the raw responses and
[VERIFY.md](VERIFY.md) for the exact commands and output.

---

## Configuration

All settings live in `.env` (never committed). See [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | Enables Gemini narratives. Get one at <https://aistudio.google.com/apikey> |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model id |
| `GEMINI_ENABLED` | `true` | Set `false` to force the deterministic fallback |
| `DATABASE_URL` | `sqlite:///./data/scamshield.db` | PostgreSQL: `postgresql+psycopg://user:pass@host:5432/db` |
| `STORE_RAW_MESSAGE` | `true` | `false` = never persist plaintext (redacted preview only). **Use `false` in production.** |
| `WEB_CONCURRENCY` | `2` | uvicorn workers in the production profile / Dockerfile |
| `PRIVACY_SALT` | *(change me)* | Salt for the message fingerprint hash |
| `HISTORY_MAX_ROWS` | `5000` | Retention ceiling; oldest rows are trimmed |
| `API_KEY` | *(empty)* | If set, `/scan/*` and `/history/*` require `X-API-Key` |
| `ML_SPAM_THRESHOLD` | `0.5` | Decision boundary for the spam label |
| `CORS_ORIGINS` | `http://localhost:8501,…` | Comma-separated allowed browser origins |

**The app runs fully without a Gemini key** — it just uses the built-in explanations.

---

## API reference

Interactive docs at <http://localhost:8000/docs>. Full examples: [docs/API.md](docs/API.md).

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Status of API, DB, model, Gemini |
| `POST` | `/api/v1/scan/message` | Full three-layer analysis |
| `POST` | `/api/v1/scan/url` | URL analysis only (ML skipped by design) |
| `POST` | `/api/v1/scan/batch` | Up to 20 messages |
| `GET` | `/api/v1/scan/rules` | Full rule catalogue (transparency) |
| `GET` | `/api/v1/scan/explain-scoring` | Published weights & thresholds |
| `GET` | `/api/v1/history` | Paginated history with filters |
| `GET` | `/api/v1/history/stats` | Dashboard aggregates + model metrics |
| `GET` | `/api/v1/history/{id}` | One scan (raw text needs `?include_raw=true`) |
| `DELETE` | `/api/v1/history` | Clear all history |
| `GET` | `/api/v1/history/export.csv` | CSV export |
| `GET` | `/api/v1/models/comparison` | Algorithm comparison (real metrics) |
| `GET` | `/api/v1/models/info` | Active artefact metadata + limitations |
| `GET` | `/api/v1/models/terms` | Strongest spam/ham terms (interpretability) |
| `GET` | `/api/v1/samples` | Curated demo inputs |

```powershell
# Example: analyse a message
curl -X POST http://localhost:8000/api/v1/scan/message `
  -H "Content-Type: application/json" `
  -d '{\"text\":\"Dear Customer, your SBI KYC is suspended. Update at http://sbi-kyc-verify.xyz/login within 24 hours.\",\"language\":\"en\"}'
```

Abbreviated response:

```json
{
  "risk": {"level": "critical", "score": 100, "headline": "Do not interact with this message"},
  "rule_engine": {"score": 100, "matched_count": 9},
  "ml_prediction": {"label": "spam", "spam_probability": 0.9168,
                    "note": "…not a guarantee that the message is fraudulent (or safe)…"},
  "urls": {"urls_found": 1, "highest_score": 67,
           "analyses": [{"registered_domain": "sbi-kyc-verify.xyz", "lookalike_of": "sbi"}]},
  "explanation": {"source": "fallback", "language": "en", "recommendations": ["…"]}
}
```

---

## Testing

```powershell
pytest -q                       # 250 tests, ~5 s
pytest -q --cov=backend --cov=ml --cov-report=term   # 79% coverage
pytest tests/test_phase5_url.py -v                   # one phase
```

| File | Tests | Covers |
|---|---|---|
| `test_phase1_foundation.py` | 22 | Config, DB bootstrap, error envelope, privacy helpers |
| `test_phase1_frontend.py` | 4 | Streamlit `AppTest`: app runs, navigation, no exceptions |
| `test_phase2_rules.py` | 46 | Normalisation, every rule family, precision regressions, scoring bounds |
| `test_phase3_ml.py` | 24 | Cleaning, dataset shape, **measured** metric floors, persistence, inference |
| `test_phase4_gemini.py` | 22 | Fallbacks in 3 languages, prompt redaction, JSON parsing, stubbed failures |
| `test_phase5_url.py` | 38 | Every URL check + **`test_never_makes_network_calls`** (patches `socket`) |
| `test_phase5_integration.py` | 52 | Full HTTP pipeline, batch, validation, history, stats, golden sample expectations |
| `test_phase7_security.py` | 30 | Secret leakage, privacy controls, injection payloads, API-key auth, retention, concurrency |
| `test_phase9_deploy.py` | 12 | `PORT` binding, blank `DATABASE_URL` fallback, `DATA_DIR`, first-boot seeding idempotency, Dockerfile/blueprint consistency, model artefacts present |

Notable tests:

* **`test_never_makes_network_calls`** — monkeypatches `socket.connect` and asserts the URL
  analyser never calls it. The safety claim in the docstring is *enforced*, not just stated.
* **`test_every_sample_matches_its_expected_risk`** — golden-file test over all 11 demo
  samples: the risk level shown in the slides must match what the code produces.
* **`test_scoring_weights_match_the_code`** — the weights published by
  `/scan/explain-scoring` must equal `Severity.weight`, so docs cannot drift.
* **`test_known_false_positive_is_documented`** — locks in the documented false positive.
* **`test_dockerfile_binds_to_platform_port`** — fails if the container ever hardcodes
  `8000` again, which would break Render's health check.
* **`test_seeding_skips_when_history_not_empty`** — a redeploy must not duplicate the
  demo scans across workers.

---

## Honest limitations

**The ML model does not understand Hindi or Hinglish.**

| Layer | English | Hindi | Hinglish |
|---|---|---|---|
| ML classifier | ✅ trained on it | ❌ not trained | ❌ not trained |
| Rule engine | ✅ full rule set | ⚠️ curated keywords | ⚠️ curated keywords |
| Explanation | ✅ | ✅ | ✅ |

The UCI SMS Spam Collection is English-only. For a Hinglish scam the model returns a
*low* probability while the rules score 100/100 — the UI shows both numbers side by side
rather than hiding the disagreement. A multilingual training pipeline is designed in
[docs/FUTURE_SCOPE.md](docs/FUTURE_SCOPE.md).

**A documented false positive we did not hide.** A genuine SBI debit alert
(`Rs.1250.00 debited from A/c XX1234 … Balance 12000.00`) scores **MEDIUM (20/100)**,
because the 2005-era model has rarely seen transactional alerts and returns P(spam)=0.82.
We mitigated it with a structural "genuine transaction alert" rule that damps the ML
component when no high-severity rule fires — but it still lands at MEDIUM, and the sample
carries a `note` explaining exactly why. We deliberately did **not** tune thresholds until
it read LOW.

**Other limits:** rules are finite and can be out-phrased; URL analysis never fetches the
page so a compromised legitimate domain passes; Gemini explains but never detects; the risk
score is a documented heuristic, **not** a calibrated probability.

Full discussion: [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

---

## Security & privacy

| Control | Implementation |
|---|---|
| Secret hygiene | Only `config.py` reads env vars; secrets never appear in any response (tested) |
| Redaction | Phone, email, card, OTP, UPI ID, IFSC, Aadhaar replaced *before* storage and *before* any Gemini call |
| Fingerprinting | Salted SHA-256 (`PRIVACY_SALT`) for duplicate detection without plaintext |
| No plaintext by default | `STORE_RAW_MESSAGE=false` disables raw storage entirely; detail endpoint requires explicit `?include_raw=true` |
| SQL injection | Every query parameterised; tested with `'; DROP TABLE scans; --` |
| Error hygiene | Structured JSON errors; tracebacks logged server-side only (tested) |
| Retention | `HISTORY_MAX_ROWS` trims the oldest rows after each write (tested) |
| Optional auth | `X-API-Key` guard on `/scan/*` and `/history/*` when `API_KEY` is set (tested) |
| User control | Clear-all / delete-one history from the UI, with confirmation |

> **Production note:** this build serves HTTP for local development. A real deployment must
> sit behind HTTPS, use OAuth2/JWT instead of a shared key, and prefer PostgreSQL.

---

## Documentation index

| Document | Contents |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Windows-first installation, troubleshooting |
| [docs/API.md](docs/API.md) | Every endpoint with request/response examples |
| [docs/OUTPUTS.md](docs/OUTPUTS.md) | Real captured output of the running deployment |
| [deploy/README.md](deploy/README.md) | Docker Compose, systemd + nginx, PaaS, env vars |
| [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) | Free Render + Streamlit Cloud deployment, step by step |
| [VERIFY.md](VERIFY.md) | Every command actually run, with its output |
| [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md) | Academic report: problem, method, results, evaluation |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 8-minute demonstration script with timings |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | What does not work and why |
| [docs/FUTURE_SCOPE.md](docs/FUTURE_SCOPE.md) | Multilingual pipeline, reputation APIs, React, PostgreSQL |
| [docs/diagrams/](docs/diagrams/) | Architecture, DFD Level 1, use case, UML class |
| [ml/evaluation/reports/](ml/evaluation/reports/) | Generated evaluation report + confusion matrix PNG |
| [docs/presentation/](docs/presentation/) | Presentation slides |

---

## Roadmap

- [x] **Phase 1** Foundation — config, DB, FastAPI, Streamlit shell *(22 tests)*
- [x] **Phase 2** Rule engine — 40+ rules, risk scoring, normalisation *(46 tests)*
- [x] **Phase 3** Machine learning — dataset, 3 models, evaluation, persistence *(21 tests)*
- [x] **Phase 4** Gemini — 3 languages, fallbacks, prompt redaction *(18 tests)*
- [x] **Phase 5** URL analysis — 15+ checks, zero network access *(82 tests)*
- [x] **Phase 6** Frontend — dashboard, analyser, URL, history, statistics, about
- [x] **Phase 7** Database, testing, security & privacy *(29 tests)*
- [x] **Phase 8** Documentation, diagrams, report, slides, demo script

---

## License

MIT — free for academic and personal use.

## Acknowledgements

* **Dataset:** [UCI Machine Learning Repository — SMS Spam Collection (id 228)](https://archive.ics.uci.edu/dataset/228/sms+spam+collection)
* **Libraries:** FastAPI, Pydantic, scikit-learn, pandas, NumPy, Streamlit, Altair, joblib, pytest
* **GenAI:** Google Gemini via the `google-genai` SDK

> ScamShield AI provides guidance, not guarantees. It cannot prove that a message or website
> is safe or fraudulent. Never share OTPs, PINs or passwords, and report financial fraud at
> **cybercrime.gov.in** or **1930** (India).
#   s c a m s h i e l d _ p r o j e c t  
 #   s c a m s h i e l d _ p r o j e c t  
 