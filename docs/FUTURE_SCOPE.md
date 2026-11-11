# ScamShield AI — Future Scope

Concrete engineering plans, not a wish list. Each item states what exists today, what is
missing, and how to build it against the current interfaces.

---

## 1. Multilingual training pipeline

**Today:** the classifier is English-only. Hindi/Hinglish detection relies on curated
keyword rules. The classifier returns ~0.07 P(spam) for a Hinglish scam.

**Target:** per-language models behind one interface, with an honest confidence signal.

### Data

| Corpus | What it gives us | Notes |
|---|---|---|
| AI4Bharat / IndicCorp | large Hindi/Hinglish text for pre-training embeddings | not labelled for spam |
| IndicNLP resources | tokenizers and normalisation for Devanagari | needed because TF-IDF on raw Devanagari is weak |
| Manually labelled set | 500–1,000 real Hinglish scam messages | the only way to get a trustworthy F1 |
| Synthetic augmentation | translate the English spam class with Gemini, then human-review | cheap, but must be reviewed or it teaches translationese |

**Plan**

```
raw Hinglish message
   ├─ transliterate to a common Latin form (or normalise Devanagari)
   ├─ language identification (fastText lid.176)
   ├─ route to the language-specific model  (en / hi / hinglish)
   └─ return label + the model name so the UI can say which model spoke
```

### Interface change (already anticipated)

`MLPrediction.model.name` already carries the model identity, and
`/api/v1/models/comparison` already reports per-model metrics, so adding a second artefact
requires **no schema change**:

```python
# backend/services/model_registry.py
def load(self, language: str = "en") -> Optional[LoadedModel]:
    return self._bundles.get(language) or self._bundles["en"]
```

### Evaluation requirement

Report per-language precision/recall. Do **not** average English and Hinglish into one
number — that would hide exactly the weakness we are trying to fix.

---

## 2. Live URL reputation (the biggest security win)

**Today:** static pattern analysis only, zero network access — a deliberate safety
decision.

**Target:** optional reputation lookups behind an explicit, user-visible toggle.

```python
# backend/services/url_analyzer.py (new module: reputation.py)
class ReputationProvider(Protocol):
    async def lookup(self, url: str) -> Optional[ReputationResult]: ...

class GoogleSafeBrowsing(ReputationProvider): ...
class VirusTotal(ReputationProvider): ...
class NullProvider(ReputationProvider):     # default, keeps today's behaviour
```

Design constraints to preserve:

* The default provider stays `NullProvider`, so the "never contacts the network" guarantee
  remains true unless the operator opts in.
* Lookups are **hash-prefix** based where the API allows it (Safe Browsing v4), so the full
  URL is never transmitted.
* Timeout of 2 s, hard failure → the static score is used and the UI says reputation was
  unavailable.
* Results are cached for 24 h; a phishing domain lives for hours, so a long TTL is harmful.

---

## 3. PostgreSQL + Alembic

**Today:** SQLite, raw `sqlite3`, SQL confined to `repositories.py`.

**Target:** production-grade concurrency and migrations.

1. Add `sqlalchemy>=2.0` and `psycopg[binary]`.
2. Introduce models mirroring the existing `scans` DDL.
3. Add Alembic; the initial revision must reproduce `SCHEMA_STATEMENTS` exactly.
4. Keep `ScanRepository`'s public methods identical, so `ScanService` never changes.
5. Parameter style: `?` (SQLite) vs `%s` (psycopg) — handled by the SQLAlchemy engine.

`DATABASE_URL` already switches engines, so the migration is contained.

---

## 4. React frontend

The architecture was designed for this: **all** data access flows through the versioned
REST API (`/api/v1`), and the Streamlit layer contains no business logic.

```
frontend-react/
├── src/
│   ├── api/            # generated from /openapi.json (openapi-typescript)
│   ├── components/     # ResultCard, RiskMeter, FindingList, UrlAnatomy
│   ├── views/          # Dashboard, Analyser, UrlAnalyser, History, Statistics
│   └── hooks/          # useScan, useHistory, useStats (TanStack Query)
```

Migration order: openapi-typescript → port `result_view` → port pages → retire Streamlit
behind a feature flag, so both UIs can run against the same backend during the transition.

---

## 5. Better modelling

| Idea | Why | Expected gain |
|---|---|---|
| Replace TF-IDF with a sentence transformer (`multilingual-e5-small`) | handles paraphrase and Hindi/Hinglish | largest single gain |
| Keep Logistic Regression on embeddings | stays interpretable via token attribution | — |
| Calibrate with `CalibratedClassifierCV` | turns scores into honest probabilities | makes `spam_probability` meaningful |
| Add hand-crafted features (link count, digits, uppercase ratio, sender-id pattern) | cheap, strong signals | small but reliable |
| Active learning loop | label the messages users mark as wrong | improves on real traffic |
| Threshold per channel (SMS vs email vs WhatsApp) | base rates differ wildly | fewer false positives |

Any of these must be evaluated on the *same* held-out split and reported next to the current
numbers — including when they lose.

---

## 6. Richer scam coverage

New rule families, each with its own curated keyword set:

* **Voice-call / vishing transcripts** (speech-to-text pipeline).
* **Investment group scams** — Telegram/WhatsApp group invite patterns.
* **Loan-app harassment** — instant-loan apps and their recovery threats.
* **Sextortion and romance scams** — image-based pressure.
* **Fake government schemes** — PM-Kisan, Ayushman Bharat impersonation.
* **QR-code replacement fraud** — merchant QR tampering.

---

## 7. Operational hardening

| Item | Implementation sketch |
|---|---|
| Rate limiting | `slowapi` with per-IP buckets; 30 scans/min by default |
| Auth | OAuth2 password flow + JWT; replace the shared `X-API-Key` |
| Observability | OpenTelemetry traces around `ScanService.scan`; Prometheus counters per layer |
| Async Gemini | move `explain()` to `async` with a shared `httpx` client and a circuit breaker |
| Caching | Redis for repeated identical scans (keyed by `content_hash`, 1 h TTL) |
| Deployment | Dockerfile + `docker compose` (api, ui, postgres, redis) |
| CI | GitHub Actions: `ruff`, `mypy`, `pytest --cov`, artefact upload |

---

## 8. Evaluation beyond the UCI dataset

The current metrics say nothing about modern Indian phishing. The missing piece is a
**contemporary labelled corpus**.

Plan:

1. Collect with consent from a university community (opt-in reporting form).
2. Redact at collection time (`privacy.redact`) — the pipeline already exists.
3. Two annotators, Cohen's κ reported for agreement.
4. Publish the splits and the labelling guide so the result is reproducible.
5. Report: per-category recall, per-language recall, false-positive rate on genuine bank
   alerts, and a calibration curve.

**This is the single most valuable future contribution:** a model is only as good as the
data it is judged on.

---

## 9. Accessibility & inclusion

* Screen-reader-friendly result summary (risk, action, confidence) at the top of the page.
* Voice output of the recommendations in Hindi/English for low-literacy users.
* WhatsApp bot interface — the channel where most Indian scams actually arrive.
* Offline-first mobile app with an on-device model (the 162 KB LR artefact is small enough).
