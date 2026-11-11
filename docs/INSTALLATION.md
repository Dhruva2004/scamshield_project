# ScamShield AI — Installation Guide

Written for **Windows** first (the most common SIC/lab setup), with macOS/Linux notes.
Every command has been run against this codebase on Python 3.13.

---

## 0. Prerequisites

| Requirement | Version | How to check |
|---|---|---|
| Python | 3.10 – 3.13 | `python --version` |
| pip | bundled with Python | `python -m pip --version` |
| Git | any | `git --version` |
| Internet | only for install, dataset download, and Gemini | — |

> **Windows tip:** during Python installation tick **"Add python.exe to PATH"**.

If `python` opens the Microsoft Store, use `py -3` instead of `python` throughout.

---

## 1. Get the project

```powershell
# From a ZIP
Expand-Archive ScamShield-AI.zip -DestinationPath .
cd ScamShield-AI

# Or from Git
git clone <your-repo-url>
cd ScamShield-AI
```

---

## 2. Create a virtual environment

A virtual environment isolates this project's packages from the rest of your system.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**If PowerShell blocks activation:**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Alternative shells:

```cmd
:: cmd.exe
.venv\Scripts\activate.bat
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

You should now see `(.venv)` at the start of your prompt.

---

## 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

This installs roughly 25 packages (~250 MB), most of which is Streamlit's dependency tree.

Verify:

```powershell
python -c "import fastapi, streamlit, sklearn, pandas; print('dependencies OK')"
```

**Optional extras**

```powershell
pip install matplotlib      # only needed for the confusion-matrix PNG
```

---

## 4. Create the environment file

```powershell
Copy-Item .env.example .env
```

Then open `.env` in a text editor and set at minimum:

```ini
PRIVACY_SALT=paste-a-long-random-string-here
```

To enable Gemini explanations (optional — the app works without it):

```ini
GEMINI_API_KEY=your-key-from-https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.0-flash
```

> **Never commit `.env`.** It is already listed in `.gitignore`.

Confirm the configuration loads:

```powershell
python -m backend.config
```

Expected output (paths will differ):

```
{
  "app_name": "ScamShield AI",
  "environment": "development",
  "database_backend": "sqlite",
  "model_available": false,
  "gemini_configured": false
}
```

`model_available: false` is correct at this stage — you have not trained yet.

---

## 5. Download the dataset

```powershell
python -m ml.data.download_dataset
```

Expected output:

```
[download] Saved 203,415 bytes -> …\ml\data\raw\sms_spam_collection.zip
[extract] SMSSpamCollection -> …\ml\data\raw\SMSSpamCollection

[prepare] Dataset summary
  raw rows              : 5,574
  duplicates removed    : 414
  final rows            : 5,158
  ham / spam            : 4,516 / 642
  spam share            : 12.44%
```

**Offline?** Download
<https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip> manually, save it as
`ml\data\raw\sms_spam_collection.zip`, and re-run the command.

---

## 6. Train the model

```powershell
python scripts/train_models.py
```

Expected output (values are deterministic with `random_state=42`):

```
[data] loaded 5,158 messages from sms_spam.csv
[tfidf] vocabulary: 9,629 features
[split] train: 4,126 | test: 1,032

[train] MultinomialNB ...
        accuracy=0.9845 precision=0.9828 recall=0.8906 f1=0.9344 auc=0.9896
[train] LogisticRegression ...
        accuracy=0.9855 precision=0.9520 recall=0.9297 f1=0.9407 auc=0.9985
[train] RandomForest ...
        accuracy=0.9864 precision=0.9750 recall=0.9141 f1=0.9435 auc=0.9982

[winner] LogisticRegression
[save] model_logistic_regression.joblib (162 KB)
[save] metrics.json
```

Artefacts created:

| File | Purpose |
|---|---|
| `models/model_logistic_regression.joblib` | classifier + vectorizer + metadata bundle |
| `models/metrics.json` | real metrics read by the dashboard |
| `ml/vectorizers/tfidf_vectorizer.joblib` | vectorizer on its own |

---

## 7. Evaluate (optional, for the report)

```powershell
python -m ml.evaluation.evaluate
```

Writes:

* `ml/evaluation/reports/evaluation_report.md`
* `ml/evaluation/reports/evaluation_report.json`
* `ml/evaluation/reports/confusion_matrix.png` *(needs matplotlib)*

---

## 8. Run the test suite

```powershell
pytest -q
```

Expected: `250 passed`. With coverage:

```powershell
pip install pytest-cov
pytest -q --cov=backend --cov=ml --cov-report=term
```

Expected: `TOTAL … 79%`.

---

## 9. Start the application

### One command

```powershell
python scripts/run_dev.py
```

### Or two terminals

```powershell
# Terminal 1 — backend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

```powershell
# Terminal 2 — frontend
streamlit run frontend/app.py
```

Open:

* Dashboard → <http://localhost:8501>
* API docs → <http://localhost:8000/docs>

### Optional: seed demo data for a presentation

```powershell
python scripts/seed_demo_data.py --clear
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `'python' is not recognised` | PATH not set | Reinstall Python with "Add to PATH", or use `py -3` |
| `Activate.ps1 cannot be loaded` | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `ModuleNotFoundError: No module named 'backend'` | Running from the wrong folder | `cd` into `ScamShield-AI`, or set `$env:PYTHONPATH="."` |
| `uvicorn` / `streamlit` not recognised | Scripts folder not on PATH | Use `python -m uvicorn …` / `python -m streamlit …` |
| Dashboard says **API offline** | Backend not running | Start it on port 8000 |
| `model_available: false` after training | Stale process cache | Restart the backend |
| Gemini text says "Automated explanation (Gemini not used)" | No key / disabled | Set `GEMINI_API_KEY` and restart |
| `Port 8000 already in use` | Another process | `uvicorn … --port 8001` and set `API_BASE_URL=http://localhost:8001` |
| `Port 8501 already in use` | Another Streamlit app | `streamlit run frontend/app.py --server.port 8502` |
| Dataset download fails | Network/proxy | Use the manual offline method in step 5 |
| `pytest` cannot import `tests` | Running outside the project root | Run `pytest` from `ScamShield-AI`, not from `tests/` |

### Resetting everything

```powershell
# wipe the database, models and generated data, then rebuild
Remove-Item data\scamshield.db -ErrorAction SilentlyContinue
Remove-Item models\*.joblib, models\metrics.json -ErrorAction SilentlyContinue
python scripts/train_models.py
```

---

## Uninstall

```powershell
deactivate
Remove-Item -Recurse -Force .venv
```
