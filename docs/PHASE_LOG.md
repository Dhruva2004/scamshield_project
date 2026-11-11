# ScamShield AI — Build Log (phases 1–8)

What was built in each phase, what broke, and how it was fixed. This is the "how it was
actually done" record — useful for the report's methodology section and for anyone extending
the project.

---

## Phase 1 — Foundation ✅

**Built:** `config.py` (pydantic-settings), logging, exception handlers, SQLite schema,
repositories, health/history routers, `main.py`, Streamlit shell, `theme.css`, `api_client.py`.

**Issues found and fixed**

| Issue | Cause | Fix |
|---|---|---|
| `SettingsError: error parsing value for field "cors_origins"` | `pydantic-settings` tries to JSON-decode `List` fields from `.env` | Store as a comma-separated `str`, expose `cors_origin_list` |
| `model_available` path wrong when run from another directory | Relative `./models` | Validator resolves all project paths against `PROJECT_ROOT` |
| `GET /` returned 404 | Landing route was mounted inside a prefixed router | Registered on the app instead |
| `ValidationError` for `StatsResponse.model_performance` | A duplicate `ModelPerformance` class shadowed the other | Deleted the duplicate; `schemas/history.py` imports from `schemas/evaluation.py` |
| Routers appeared missing when introspecting `app.routes` | FastAPI 0.162 nests included routers lazily (`_IncludedRouter`) | Verify through `app.openapi()["paths"]` instead |

Result: **22 tests passing.**

---

## Phase 2 — Rule engine ✅

**Built:** `normalize.py` (de-obfuscation), `rule_catalog.py` (40+ rules, 8 combinations),
`rule_engine.py` (category de-duplication, context cap, severity floor), privacy service.

**Issues found and fixed**

| Issue | Cause | Fix |
|---|---|---|
| `canonicalize("24 hrs")` → `"2a hrs"`; OTP `482913` → `ab2gie` | Leetspeak folding applied to every character | Fold only inside tokens with ≥3 letters and more letters than digits; skip tokens containing `@` (UPI IDs) |
| Genuine debit alert matched `R_UNKNOWN_ACCOUNT` | The VPA pattern matched the *recipient* of a completed debit | Require a payment verb before the VPA |
| Genuine debit alert scored 38 (MEDIUM) | Amount-only payment rule fired on any `Rs.` mention | Require an actual instruction to pay; add the weight-0 transactional-structure rule |
| One CRITICAL rule produced only MEDIUM overall | No floor | Added the documented severity floor (1 critical → ≥65, 2+ → ≥75) |
| Published weights (30) ≠ code weights (32) | Drifted during editing | Aligned `Severity.weight`; added a test that compares the API response with the enum |

Result: **46 tests passing.**

---

## Phase 3 — Machine learning ✅

**Built:** dataset download/cleaning, `text_clean.py`, `train.py` (3 algorithms, stratified CV,
metrics, persistence), `predictor.py`, `evaluate.py`.

**Measured outcome:** LR accuracy 0.9855, precision 0.9520, recall 0.9297, F1 0.9407,
ROC-AUC 0.9985. RF had the highest raw F1 (0.9435) — **0.0028 higher**, inside the CV noise
band — so a declared tie-break (ROC-AUC, then simplicity) selected Logistic Regression.

**Issues found and fixed**

| Issue | Cause | Fix |
|---|---|---|
| 5,174 rows in the first run vs 5,158 later | Cleaning dropped rows that cleaned to empty strings | Documented; the number in the report matches the code path exactly |
| "Best F1 wins" selected a 3.3 MB forest over a 162 KB linear model on noise | Naive argmax | Introduced `F1_TIE_TOLERANCE = 0.01` with the reasoning recorded in `selection_reason` |

Result: **24 tests passing** (with metric floors, so a regression in quality fails the suite).

---

## Phase 4 — Gemini ✅

**Built:** `gemini_service.py` with modern + legacy SDK support, prompt redaction, defensive
JSON parsing, and deterministic fallbacks in three languages.

**Design decision:** Gemini is never on the critical path. Tested with a stubbed client for
success, exception, unparsable output and missing fields.

Result: **22 tests passing.**

---

## Phase 5 — URL analysis ✅

**Built:** `url_analyzer.py` with 15+ checks, punycode decoding, homoglyph unmasking, brand
allow-lists.

**Issues found and fixed**

| Issue | Cause | Fix |
|---|---|---|
| `192.168.4.7` parsed as TLD `7`, reg `4.7` | `_split_host` ran on IP literals | Skip domain splitting when the host is an IP |
| `.apk` in the *host* not detected | Executable check looked only at the path | Check `hostname + path`, add the double-extension pattern |
| `аpple.com` (Cyrillic а) not identified as an Apple look-alike | Brand match ran on the raw hostname | Decode punycode, then map homoglyphs, then match |
| `xn--pypal-4ve.com` not linked to PayPal | Punycode payload decoded instead of the full label | `label.encode("ascii").decode("idna")` |
| `Pydantic ValidationError: path should be a string` | A positional `_build_info(...)` call passed `[]` into `path` | Switched the early returns to keyword arguments |
| Genuine `https://www.sbi.co.in/web/personal-banking` flagged | The lookalike regex matched the *path* | Anchor the pattern at the TLD boundary; the authoritative check stays in the URL analyser |

Result: **90 tests passing** (38 unit + 52 integration).

---

## Phase 6 — Frontend ✅

**Built:** dark theme, `ui.py` primitives, Altair charts, `result_view.py`, and six pages.

**Verification:** Streamlit `AppTest` drives the real app — navigation across all six pages,
clicking a demo sample, running an analysis, then confirming the scan appears in History and
the Dashboard KPI. Zero exceptions on every page.

**Polish:** replaced `use_container_width=True` with `width="stretch"` (Streamlit deprecation),
and removed private `_request` access from pages by adding typed client functions.

---

## Phase 7 — Database, tests, security ✅

**Built:** retention policy, security test suite, seeding script, run script.

**Issues found and fixed**

| Issue | Cause | Fix |
|---|---|---|
| **Privacy leak:** `GET /history/{id}` returned `raw_message` | The row dict was returned unfiltered | Added `HistoryDetail` (no raw field) + explicit `?include_raw=true` opt-in, gated on `STORE_RAW_MESSAGE` |
| `cross_validation` schema rejected a string note | Declared as `Dict[str, float]` | Changed to `Dict[str, Any]` |

Coverage: **79%** of `backend/` + `ml/`.

---

## Phase 8 — Documentation ✅

README, installation guide, API reference, project report, limitations, future scope, folder
reference, samples with verified outputs, four diagrams (SVG), and a 15-slide deck (PPTX).

---

## Verification summary

| Phase | Tests | Cumulative |
|---|---|---|
| 1 | 22 (+4 frontend) | 26 |
| 2 | 46 | 72 |
| 3 | 24 | 96 |
| 4 | 22 | 118 |
| 5 | 90 | 208 |
| 7 | 30 | 250 |

