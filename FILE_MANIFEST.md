# ScamShield AI — complete file manifest

Every file in the delivered project.

| Measure | Count |
|---|---|
| **Workspace project files** | **127** (excluding `.env`, caches and the local database) |
| + `.env` (secrets, local only) | 128 |
| **Files uploaded to GitHub** (`.env` excluded) | **126** |
| Files in `ScamShield-AI.zip` | 159 (includes empty-marker `.gitkeep` files and this manifest) |

Counts differ between the workspace and the ZIP because the ZIP also carries
`.gitkeep` placeholders for empty folders. Nothing else is added or removed.

## Root (9 files)

| File | Purpose |
|---|---|
| `README.md` | Main documentation: features, measured results, architecture, install, deployment, testing |
| `VERIFY.md` | Every command actually run in this environment, with its real output |
| `render.yaml` | Render Blueprint — one-click cloud deploy (Docker, health check, env vars) |
| `requirements.txt` | All Python dependencies, pinned by minimum version |
| `pytest.ini` | Test configuration (test paths, markers, warning filters) |
| `.env.example` | Environment template — copy to `.env` and fill in |
| `.gitignore` | Excludes secrets, databases, caches, and model binaries |
| `.streamlit/config.toml` | Streamlit server/theme config (dark theme, headless, port 8501) |

> `.env` is present in the workspace but deliberately **not shipped** — it holds your
> secrets. Copy `.env.example` instead.

## backend/ — the API (31 files)

### `backend/`
| File | Purpose |
|---|---|
| `main.py` | FastAPI app: lifespan, CORS, gzip, request-ID middleware, production runner, **first-boot demo seeding** |
| `config.py` | Pydantic settings: `.env` loading, `PORT`/`DATA_DIR` support, secrets redaction |
| `__init__.py` | Package marker |

### `backend/api/` — HTTP layer only (7 files)
| File | Purpose |
|---|---|
| `scan.py` | `POST /scan/message`, `/scan/url`, `/scan/batch`, `GET /scan/rules`, `/scan/explain-scoring` |
| `history.py` | History list/detail/delete, CSV export, statistics; **raw text gated** behind `include_raw` |
| `models.py` | Model info, algorithm comparison, top TF-IDF terms |
| `health.py` | `/health` with per-component status |
| `samples.py` | 11 curated demo messages with their expected risk levels |
| `dependencies.py` | Shared dependencies (API-key auth, pagination) |

### `backend/services/` — business logic (9 files)
| File | Purpose |
|---|---|
| `scan_service.py` | Orchestrates the whole pipeline: rules → ML → URL → fusion → explanation → persist |
| `rule_catalog.py` | **37 detection rules** across 19 categories, each with severity, pattern, and explanation |
| `rule_engine.py` | Runs rules over normalised text, returns findings + score |
| `risk_assessor.py` | Fusion maths: `max(rule, ml, url)` + agreement bonus, thresholds, actions |
| `url_analyzer.py` | 15 URL checks — shorteners, lookalikes, IP hosts, userinfo trick — **never makes network calls** |
| `gemini_service.py` | Gemini explanations in EN/HI/Hinglish with full fallback chain |
| `model_registry.py` | Loads/caches the `.joblib` model and vectorizer |
| `privacy.py` | Redaction (OTP/PAN/phone/email), salted hashing, retention |
| `__init__.py` | Package marker |

### `backend/schemas/` — Pydantic contracts (5 files)
`scan.py` (request/response models), `history.py` (redacted detail), `evaluation.py`, `common.py` (enums: Language, RiskLevel), `__init__.py`

### `backend/database/` — persistence (3 files)
| File | Purpose |
|---|---|
| `connection.py` | Schema definition + **self-healing** `_ensure_schema()` (recreates tables if the DB is deleted) |
| `repositories.py` | All SQL, parameterised; never f-string interpolation |
| `__init__.py` | Package marker |

### `backend/core/` (3 files)
`exceptions.py` (consistent JSON error envelope), `logging_config.py`, `__init__.py`

### `backend/models/`
`__init__.py` — reserved for future ORM models

## frontend/ — the Streamlit dashboard (18 files)

| File | Purpose |
|---|---|
| `app.py` | Entry point: page config, sidebar navigation, routing |
| `api_client.py` | **The only module that speaks HTTP** — timeouts, error translation, API key |
| `components/ui.py` | Reusable HTML/CSS blocks: risk meter, badges, cards, disclaimers |
| `components/charts.py` | Altair charts: risk distribution, trends, model comparison |
| `components/result_view.py` | Renders one scan result with the **three layers kept visually separate** |
| `views/dashboard.py` | KPIs, risk distribution, recent scans, model performance |
| `views/analyser.py` | Message analysis with language selection and sample loader |
| `views/url_page.py` | URL analysis — states it never opens the link |
| `views/history_page.py` | Paginated, searchable, filterable history; clear-history behind confirmation |
| `views/statistics_page.py` | Aggregate stats, top indicators, trends |
| `views/about_page.py` | Architecture, language-support matrix, honest limitations |
| `styles/theme.css` | Custom dark theme |
| `.streamlit/secrets.toml.example` | Template for Streamlit Cloud (`API_BASE_URL`, `API_KEY`) |
| `__init__.py`, `components/__init__.py`, `views/__init__.py` | Package markers |

## ml/ — the machine-learning pipeline (16 files)

| File | Purpose |
|---|---|
| `data/download_dataset.py` | Reproducible UCI SMS Spam Collection download + cleaning |
| `data/raw/SMSSpamCollection` | **The real dataset** — 5,572 rows (4,827 ham / 747 spam) |
| `data/raw/sms_spam_collection.zip` | Original archive, kept for provenance |
| `data/processed/sms_spam.csv` | Cleaned, de-duplicated, split-ready CSV |
| `preprocessing/normalize.py` | De-obfuscation for the RULE engine (leetspeak, spacing tricks) |
| `preprocessing/text_clean.py` | Lighter cleaning for the ML model |
| `training/train.py` | Trains 3 algorithms, stratified 5-fold CV, real metrics, saves artefacts |
| `inference/predictor.py` | `MLPrediction` + per-token explanations |
| `evaluation/evaluate.py` | Re-scores the saved artefact, writes the report and confusion matrix |
| `evaluation/reports/evaluation_report.md` | Human-readable evaluation |
| `evaluation/reports/evaluation_report.json` | Machine-readable metrics |
| `evaluation/reports/confusion_matrix.png` | Confusion matrix image for the report |
| `vectorizers/tfidf_vectorizer.joblib` | Fitted TF-IDF vectorizer |
| `__init__.py` × 5 | Package markers |

## models/ (3 files)
| File | Purpose |
|---|---|
| `model_logistic_regression.joblib` | **The shipped model** (164 KB) — LR, F1 0.9407 |
| `metrics.json` | Measured metrics for all 3 algorithms + selection reasoning |
| `.gitkeep` | Keeps the folder in Git |

## tests/ — 250 tests (11 files)

| File | Tests | Covers |
|---|---|---|
| `test_phase1_foundation.py` | 22 | Config, DB bootstrap, error envelope, privacy helpers |
| `test_phase1_frontend.py` | 4 | Streamlit `AppTest`: app runs, navigation, no exceptions |
| `test_phase2_rules.py` | 46 | Normalisation, every rule family, precision regressions, score bounds |
| `test_phase3_ml.py` | 24 | Cleaning, dataset shape, measured metric floors, persistence, inference |
| `test_phase4_gemini.py` | 22 | Fallbacks in 3 languages, prompt redaction, JSON parsing, stubbed failures |
| `test_phase5_url.py` | 38 | Every URL check + **`test_never_makes_network_calls`** (patches `socket`) |
| `test_phase5_integration.py` | 52 | Full HTTP pipeline, batch, validation, history, stats, golden samples |
| `test_phase7_security.py` | 30 | Secret leakage, privacy, injection payloads, API-key auth, retention, concurrency |
| `test_phase9_deploy.py` | 12 | `PORT` binding, blank `DATABASE_URL`, `DATA_DIR`, seeding idempotency, Dockerfile consistency |
| `conftest.py` | — | Isolated test database, cached-singleton reset |

## docs/ — 11 documents + 4 diagrams + 1 deck

| File | Purpose |
|---|---|
| `PROJECT_REPORT.md` | Full academic report: problem, method, results, evaluation, references |
| `START_HERE_DEPLOY.md` | **The 9-step runbook — start here.** Prereqs to verification, with expected output at each step |
| `DEPLOY_RENDER.md` | Free cloud deployment reference + troubleshooting tables |
| `PUSH_VERIFY.md` | How to prove a push worked; every rejection mode and its fix; token hygiene |
| `OUTPUTS.md` | Real captured responses from a running deployment (regenerable) |
| `SAMPLES_AND_OUTPUTS.md` | All 11 samples with their actual pipeline output |
| `API.md` | Every endpoint with request/response examples |
| `INSTALLATION.md` | Windows-first installation and troubleshooting |
| `LIMITATIONS.md` | What does not work, and why — stated plainly |
| `FUTURE_SCOPE.md` | Multilingual pipeline, reputation APIs, React, PostgreSQL |
| `DEMO_SCRIPT.md` | 8-minute presentation walkthrough with timings |
| `FOLDER_STRUCTURE.md` | This structure, explained |
| `PHASE_LOG.md` | Build history: what was done in each of the 8 phases |
| `diagrams/architecture.svg` | System architecture |
| `diagrams/dfd_level1.svg` | Data flow diagram, level 1 |
| `diagrams/use_case.svg` | Use case diagram |
| `diagrams/uml_classes.svg` | UML class diagram |
| `presentation/ScamShield_AI_Slides.pptx` | 15-slide presentation |

## deploy/ (7 files)

| File | Purpose |
|---|---|
| `Dockerfile.api` | Multi-stage, non-root uid 1001, healthcheck, `$PORT` binding, 2 workers |
| `Dockerfile.ui` | Streamlit image |
| `docker-compose.yml` | api + ui + optional `postgres` profile, named data volume |
| `nginx.conf` | TLS, HSTS, CSP, 30 r/m rate limit, Streamlit WebSocket upgrade map |
| `scamshield-api.service` | systemd unit (hardened, `ProtectSystem=strict`) |
| `scamshield-ui.service` | systemd unit (hardened) |
| `README.md` | The three deployment paths + full environment-variable reference |

## scripts/ (7 files)

| File | Purpose |
|---|---|
| `train_models.py` | One-command training |
| `seed_demo_data.py` | Populate the dashboard via the real pipeline (`--clear` to reset) |
| `run_dev.py` | Start backend + frontend together, supervised |
| `prod_smoke_test.py` | Post-deploy verification, 12 checks, exit code 0/1 |
| `capture_outputs.py` | Regenerate `docs/OUTPUTS.md` from a live API |
| `export_for_git.py` | Git-ready export — force-includes the `.joblib` files that `.gitignore` excludes |
| `deploy_step1_prepare.ps1` | Windows one-command Step 1: checks env, trains if needed, builds the export |
| `deploy_step2_push.ps1` | Windows one-command Step 2: repairs `origin`, commits, pushes, verifies the commit |
| `deploy_onepaste.ps1` | Single-paste variant: prompts for username/repo, then does everything |
| `__init__.py` | Package marker |

## data/ (1 file)
`exports/.gitkeep` — runtime output folder for CSV exports. The SQLite database is created here on first run and is **not** shipped (it would contain scan history).

---

## What is NOT in this archive, and why

| Missing | Reason | How to get it |
|---|---|---|
| `.env` | Contains secrets — never shipped | `cp .env.example .env` then edit |
| `data/scamshield.db` | Your scan history; created automatically on first start | Nothing to do |
| `models/model_random_forest.joblib` | Removed to keep the archive small; its metrics are preserved in `metrics.json` | `python scripts/train_models.py` |
| `dist/git-export/` | Generated by `scripts/export_for_git.py` when you deploy | Run that script |
| `__pycache__/`, `.coverage` | Caches, not source | Regenerated |

## Quick start after extracting

```bash
cd ScamShield-AI
python -m venv .venv
# Windows:  .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
pytest -q                     # expect: 250 passed
python scripts/run_dev.py     # API on :8000, dashboard on :8501
```
