# ScamShield AI — Folder & File Reference

Every directory and every significant file, with its purpose and the reason it exists as a
separate unit. Use this as the map when marking the project.

```
ScamShield-AI/
```

## Root

| File | Purpose |
|---|---|
| `README.md` | Entry point: what it does, measured results, install, run, testing, limitations |
| `requirements.txt` | Pinned dependency ranges, grouped by concern with comments |
| `.env.example` | Template for every configuration variable — copied to `.env`, which is git-ignored |
| `.gitignore` | Excludes secrets, databases, model binaries and generated data |
| `pytest.ini` *(optional)* | Test configuration (paths, markers) |

## `backend/` — the API

| Path | Purpose | Why separate |
|---|---|---|
| `main.py` | FastAPI app, middleware (CORS, gzip, request-id), lifespan, router wiring | The only place the app is assembled |
| `config.py` | `pydantic-settings` model reading `.env`; absolute-path resolution; redacted `describe()` | Single source of truth for configuration; nothing else reads `os.environ` |
| `api/dependencies.py` | Optional `X-API-Key` guard | Cross-cutting concerns in one place |
| `api/health.py` | `/health` and `/` | Monitors and the UI footer poll this |
| `api/scan.py` | `/scan/message`, `/scan/url`, `/scan/batch`, `/scan/rules`, `/scan/explain-scoring` | Thin HTTP layer only |
| `api/history.py` | History CRUD, `/stats`, `/export.csv` | Read-only analytics separated from scanning |
| `api/models.py` | `/models/comparison`, `/models/info`, `/models/terms` | Model transparency endpoints |
| `api/samples.py` | Curated demo inputs | UI and slides read the same list, so they cannot disagree |
| `core/logging_config.py` | One log format for the process | Consistent, greppable logs |
| `core/exceptions.py` | Domain exceptions → structured JSON; no tracebacks leak | Error hygiene is a security control |
| `schemas/common.py` | `RiskLevel`, `ScanType`, `Language`, `Severity` (+weights) | Enums shared by API, services and tests |
| `schemas/scan.py` | Request/response contracts | The API shape; the frontend depends on it |
| `schemas/history.py` | `HistoryItem/Detail/Page`, `StatsResponse`, `HealthResponse` | `HistoryDetail` deliberately omits `raw_message` by default |
| `schemas/evaluation.py` | `ModelPerformance`, `ModelComparison*` | One definition, imported by both history and models routers |
| `services/scan_service.py` | Orchestrator: privacy → rules → ML → URLs → risk → explanation → persist | Business logic testable without HTTP |
| `services/rule_catalog.py` | 40+ `RuleSpec` objects + combinations + brand lists | Data, not logic: an analyst edits this file only |
| `services/rule_engine.py` | Matching, category de-duplication, severity floor, scoring | The algorithm, independent of the rule data |
| `services/url_analyzer.py` | 15+ static URL checks; publishes a no-network contract | Safety-critical module, isolated and heavily tested |
| `services/risk_assessor.py` | Fusion policy, reasons, recommended actions | The only place all three layer outputs meet |
| `services/gemini_service.py` | Gemini client, prompt construction, JSON parsing, deterministic fallback | The optional dependency never enters the critical path |
| `services/model_registry.py` | Lazy joblib loading, `predict_proba`, metrics access | Model failures are non-fatal by construction |
| `services/privacy.py` | Redaction, salted hashing, retention payload | Privacy rules in one auditable file |
| `database/connection.py` | Schema DDL, PRAGMAs, context-managed connections | The only place a connection is opened |
| `database/repositories.py` | All SQL | Swapping SQLite for PostgreSQL touches this file only |
| `models/` | Reserved namespace for future ORM models | Keeps `database/` free of ORM concerns today |

## `frontend/` — the UI

| Path | Purpose |
|---|---|
| `app.py` | Page config, sidebar navigation, routing, global error guard |
| `api_client.py` | **The only module that speaks HTTP.** Typed wrappers + one `APIError` type |
| `components/ui.py` | HTML/CSS primitives: metric cards, risk pills, meters, finding rows (all `html.escape`d) |
| `components/charts.py` | Altair builders: risk donut, daily trend, indicator bars, model comparison |
| `components/result_view.py` | Renders one scan with the three layers kept visibly separate |
| `views/dashboard.py` | KPI cards, charts, recent scans, model panel |
| `views/analyser.py` | Message analyser with demo picker and language selector |
| `views/url_page.py` | URL analyser, URL anatomy card, "read a domain correctly" tutorial |
| `views/history_page.py` | Filtering, detail view, CSV export, delete / clear-all |
| `views/statistics_page.py` | Algorithm comparison, learned terms, honest limitations |
| `views/about_page.py` | Architecture, language-support matrix, known limitations |
| `styles/theme.css` | The dark cybersecurity theme (injected via `ui.inject_theme`) |
| `locales/` | Reserved for future i18n message catalogues |

## `ml/` — the machine learning

| Path | Purpose |
|---|---|
| `data/download_dataset.py` | Reproducible UCI download, extraction, de-duplication, CSV writing |
| `data/raw/` | Downloaded archive and raw text (git-ignored) |
| `data/processed/` | `sms_spam.csv` — 5,158 rows (git-ignored, regenerable) |
| `preprocessing/normalize.py` | Aggressive de-obfuscation for the **rule engine** |
| `preprocessing/text_clean.py` | Lighter cleaning for the **ML model** |
| `training/train.py` | Three algorithms, stratified CV, metrics, artefact persistence, documented selection rule |
| `evaluation/evaluate.py` | Re-scores the artefact; writes `evaluation_report.md/.json` and the confusion-matrix PNG |
| `evaluation/reports/` | Generated evidence (committed so the README can link to real numbers) |
| `inference/predictor.py` | `MLPrediction` construction plus per-token explanations for linear models |
| `vectorizers/` | `tfidf_vectorizer.joblib` (git-ignored) |

## Other directories

| Path | Purpose |
|---|---|
| `models/` | `model_*.joblib` bundles and `metrics.json` (git-ignored, regenerable) |
| `tests/` | 250 tests in 8 files + `conftest.py` fixtures (isolated temp database) |
| `docs/` | Report, installation, API, demo script, limitations, future scope, samples, diagrams, slides |
| `docs/diagrams/` | `architecture.svg`, `dfd_level1.svg`, `use_case.svg`, `uml_classes.svg` |
| `docs/presentation/` | `ScamShield_AI_Slides.pptx` (15 slides) |
| `scripts/` | `train_models.py`, `seed_demo_data.py`, `run_dev.py`, `prod_smoke_test.py`, `capture_outputs.py`, `export_for_git.py` |
| `render.yaml` | Render Blueprint: Docker build, env vars, health check, first-boot seeding |
| `deploy/` | `Dockerfile.api`, `Dockerfile.ui`, `docker-compose.yml`, `nginx.conf`, two systemd units, `README.md` |
| `docs/OUTPUTS.md` | Real HTTP responses captured from a running deployment (`scripts/capture_outputs.py`) |
| `data/` | SQLite database + CSV exports (git-ignored) |

## Design principles visible in this layout

1. **Data vs logic** — `rule_catalog.py` (rules) is separate from `rule_engine.py` (scoring);
   `model_registry.py` (loading) is separate from `predictor.py` (prediction).
2. **HTTP vs business logic** — routers validate and delegate; services decide.
3. **One boundary per external system** — `api_client.py` for HTTP, `repositories.py` for
   SQL, `gemini_service.py` for the LLM, `model_registry.py` for artefacts.
4. **Optional components are structurally optional** — a missing model, key or database
   write cannot raise out of the scan path.
5. **Evidence lives in the repository** — `metrics.json`, `evaluation_report.md` and the
   confusion-matrix PNG are committed so claims can be checked.

---

## Why `views/` and not `pages/`

Streamlit has an **automatic multipage** convention: any folder named `pages/`
sitting next to the entry-point script becomes an extra navigation menu, and each
file inside it appears as a page named after the file (`dashboard`, `analyser`,
`about page` …).

Our app does its own routing with a sidebar radio button, so those auto-generated
entries were pure noise: a second menu in the sidebar listing the same screens
under different names. Renaming the package to `views/` disables the convention
and leaves exactly one navigation control.

Nothing else changed — the modules are still plain functions called by `app.py`.
