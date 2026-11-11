# Verification Record

This file records the commands that were actually executed to validate the delivered
project, in the environment it was built in.

| Item | Value |
|---|---|
| Python | 3.13.16 |
| scikit-learn | 1.6.1 |
| pandas / NumPy | 2.2.3 / 2.3.5 |
| FastAPI / Streamlit | 0.162.2 / 1.67.0 |
| Platform | Linux x86_64 |

---

## 1. Dataset

```
$ python -m ml.data.download_dataset
[download] Saved 203,415 bytes -> ml/data/raw/sms_spam_collection.zip
[extract] SMSSpamCollection -> ml/data/raw/SMSSpamCollection
[prepare] Dataset summary
  raw rows              : 5,574
  duplicates removed    : 414
  final rows            : 5,158
  ham / spam            : 4,516 / 642
  spam share            : 12.44%
```

## 2. Training (real, deterministic, random_state=42)

```
$ python scripts/train_models.py
[data] loaded 5,158 messages from sms_spam.csv
[tfidf] vocabulary: 9,629 features
[split] train: 4,126 | test: 1,032

[train] MultinomialNB
        accuracy=0.9845 precision=0.9828 recall=0.8906 f1=0.9344 auc=0.9896
        5-fold CV F1: 0.9510 (+/- 0.0140)
[train] LogisticRegression
        accuracy=0.9855 precision=0.9520 recall=0.9297 f1=0.9407 auc=0.9985
        5-fold CV F1: 0.9372 (+/- 0.0116)
[train] RandomForest
        accuracy=0.9864 precision=0.9750 recall=0.9141 f1=0.9435 auc=0.9982
        5-fold CV F1: 0.9312 (+/- 0.0167)

[winner] LogisticRegression
        (F1 tied within tolerance; tie-break on ROC-AUC then simplicity)
[save] model_logistic_regression.joblib (162 KB)
[save] metrics.json
```

## 3. Evaluation artefacts

```
$ python -m ml.evaluation.evaluate
[evaluate] model      : LogisticRegression
[evaluate] accuracy   : 0.9855
[evaluate] precision  : 0.9520
[evaluate] recall     : 0.9297
[evaluate] f1         : 0.9407
[evaluate] roc_auc    : 0.9985

| actual \ predicted | pred ham | pred spam |
|---|---|---|
| **ham**  | 898 | 6   |
| **spam** | 9   | 119 |
```

Wrote `evaluation_report.json`, `evaluation_report.md`, `confusion_matrix.png`.

## 4. Test suite

```
$ pytest
250 passed in 5.08s

$ pytest --cov=backend --cov=ml --cov-report=term
TOTAL   2097   434   79%
```

## 5. Live API (uvicorn on :8000)

```
/api/v1/health                         200
/api/v1/samples                        200
/api/v1/scan/rules                     200
/api/v1/models/info                    200
/api/v1/models/comparison              200
/api/v1/models/terms                   200
/api/v1/history/stats                  200
/api/v1/history?page_size=3            200
POST /api/v1/scan/message              200  (critical, 100/100)
```

## 6. Frontend (Streamlit on :8501)

Verified with `streamlit.testing.v1.AppTest`, which executes the real app script:

* all six pages render with **zero exceptions**
* clicking the "KYC / bank phishing SMS" sample fills the textarea
* "Analyse message" produces a CRITICAL verdict with all three layer columns, the risk meter
  and the disclaimer
* the scan then appears in **History** and increments the **Dashboard** KPI

## 7. Demo data

```
$ python scripts/seed_demo_data.py --clear
[seed] inserted 11 scan(s)
```

---

## 8. Production profile + deployment artefacts

```
$ python scripts/prod_smoke_test.py --api http://localhost:8000 --ui http://localhost:8501
===================================================================
 ✓ API health            12 ms
 ✓   status              ok
 ✓   database            ok
 ✓   ml_model            ok
 ✓   gemini              not_configured (optional)
 ✓ Model metrics         LogisticRegression F1 0.9407 (3 algorithms compared)
 ✓ Scan scam sample      critical in 9 ms
 ✓   ML active           spam
 ✓   URL flagged         score 67
 ✓ Scan benign control   low
 ✓ Stats endpoint        224 scans
 ✓ UI health             1 ms
===================================================================
 12/12 checks passed
===================================================================
```

Load test — 200 requests, concurrency 20, **2 uvicorn workers**:

```
throughput 302 req/s | p50 39.2 ms | p95 172.0 ms | p99 488.0 ms | 0 errors
```

Zip round-trip (proves the deliverable is self-contained):

```
$ unzip -q ScamShield-AI.zip -d /tmp/final3 && cd /tmp/final3
$ cp .env.example .env
$ pytest -o addopts=""
============================= 250 passed in 5.61s ==============================
```

### What could NOT be executed in this environment

| Artefact | Status |
|---|---|
| `deploy/Dockerfile.api`, `Dockerfile.ui`, `docker-compose.yml` | Written and reviewed; **not built** — no Docker/Podman in this sandbox |
| `deploy/nginx.conf` | Written and reviewed; **not loaded** — no nginx binary |
| `deploy/scamshield-*.service` | Written and reviewed; **not started** — no systemd here |
| Production uvicorn profile (`--workers 2`, `ENVIRONMENT=production`) | **Executed and verified** — this is what the smoke test above ran against |

Run `python scripts/prod_smoke_test.py` after any real deployment; it is designed exactly
for that step and returns a non-zero exit code on failure.

---

## Regenerating everything from scratch

```powershell
python -m ml.data.download_dataset
python scripts/train_models.py
python -m ml.evaluation.evaluate
pytest
python scripts/run_dev.py

# deployment
python scripts/prod_smoke_test.py --api http://localhost:8000 --ui http://localhost:8501
python scripts/capture_outputs.py        # rewrites docs/OUTPUTS.md from live responses
```
