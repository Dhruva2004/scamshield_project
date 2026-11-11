# Deploying ScamShield AI — Render (API) + Streamlit Cloud (UI)

This is the **free, no-credit-card path**, and it is the one you chose. Follow it
top to bottom; every step has the command or the exact value to type.

You will end up with:

| Piece | URL (yours will differ) | Host |
|---|---|---|
| API + ML model | `https://scamshield-api.onrender.com` | Render (Docker) |
| Dashboard | `https://<you>-scamshield.streamlit.app` | Streamlit Community Cloud |

Total time: ~25 minutes, most of it waiting for the first build.

> **Read this first — the honest version.** Render's free plan has no persistent
> disk. The API's SQLite database lives on the container filesystem, which is
> wiped on every redeploy. The app is written to survive that (it recreates the
> schema and can reseed demo data automatically), so you never get a broken
> deployment — you just get a fresh history. Step 7 explains the ₹0 fix if you
> need real persistence.

---

## Step 0 — What you need before starting

- [ ] A GitHub account
- [ ] A Render account (<https://render.com> — sign in with GitHub)
- [ ] A Streamlit Community Cloud account (<https://share.streamlit.io> — sign in with GitHub)
- [ ] Your **Gemini API key** (<https://aistudio.google.com/apikey>) — keep it in a
      password manager, never in a file you commit

---

## Step 1 — Push the code to GitHub

### 1a. Why you cannot just `git push` the folder as-is

`.gitignore` excludes `models/*.joblib` and `ml/vectorizers/*.joblib` — they are
regenerable build artefacts, which is correct for everyday development. But the
cloud builds from Git, and **without those two files the deployed API silently
loses its ML layer** (it degrades to rules-only, by design, with no error).

The helper script below builds a Git-ready copy with exactly those artefacts
force-included, and refuses to export if anything is missing.

```powershell
cd C:\path\to\ScamShield-AI
python scripts\export_for_git.py
```

You should see:

```
PREFLIGHT
  OK    models/model_logistic_regression.joblib 162 KB
  OK    models/metrics.json                    3 KB
  OK    ml/vectorizers/tfidf_vectorizer.joblib 94 KB
  OK    deploy/Dockerfile.api                  present
  OK    render.yaml                            present
  OK    metrics.json                           3 model(s), chosen=LogisticRegression, F1=0.9407
  OK    no .env / secrets.toml                 clean
...
EXPORT
[export] 118 file(s) -> dist/git-export
[export]   included  models/model_logistic_regression.joblib
```

If any line says `FAIL`, stop and fix it — do not deploy a broken export.

> **Not sure whether your push worked?** [`PUSH_VERIFY.md`](PUSH_VERIFY.md) has one
> three-command check, plus how to tell authentication failures, non-fast-forward
> rejections and "everything up-to-date" apart — and why a successful `git push`
> still does not prove the model reached GitHub.

### 1b. Create the GitHub repository and push

Create an **empty** repo at <https://github.com/new> (no README, no .gitignore —
the export folder already has one). Call it `scamshield-ai`.

```powershell
cd dist\git-export
git init
git add -A
git commit -m "ScamShield AI - deployable snapshot"
git branch -M main
git remote add origin https://github.com/<REPLACE-WITH-YOUR-USERNAME>/scamshield-ai.git
git push -u origin main
```

> **Anything in `<ANGLE-BRACKETS>` must be replaced with your own value.**
> Pasting a placeholder literally is the single most common way this step fails —
> `git remote add` accepts it without complaint, and the failure only appears
> later at `git push` ("Repository not found").

Or skip the manual git entirely and run the automated pusher, which also repairs
a wrong `origin` from a previous attempt:

```powershell
# edit the two variables at the top of the file first
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_step2_push.ps1
```

**Verify before moving on** — this is the check that prevents the most common
failed deploy:

```powershell
git ls-files | Select-String "joblib"
```

You must see **both**:

```
ml/vectorizers/tfidf_vectorizer.joblib
models/model_logistic_regression.joblib
```

And this must print **nothing** (confirming no secrets were pushed):

```powershell
git ls-files | Select-String "^\.env$|secrets.toml"
```

---

## Step 2 — Deploy the API on Render

1. Go to <https://dashboard.render.com/blueprints>
2. **New Blueprint Instance** → connect GitHub → choose `scamshield-ai`
3. Render reads `render.yaml` and shows one service, `scamshield-api`
4. It asks for the two secrets — paste them:

   | Key | Value |
   |---|---|
   | `GEMINI_API_KEY` | your key from aistudio.google.com |
   | `API_KEY` | a long random string — generate with:<br>`python -c "import secrets;print(secrets.token_urlsafe(32))"` |

   **Save `API_KEY`**: the dashboard needs the same value in Step 4.
5. Click **Apply**. First build takes 5–10 minutes (it compiles scikit-learn).

### What Render does with the rest

Everything else is already in `render.yaml`: `ENVIRONMENT=production`,
`DEBUG=false`, 2 uvicorn workers, `STORE_RAW_MESSAGE=false` (no plaintext
persistence), a generated `PRIVACY_SALT`, and `SEED_DEMO_DATA=true` so the
dashboard is not an empty screen on first load.

### Step 2b — Wait for "Live", then verify

Render marks the service **Live** only when `/api/v1/health` returns 200. Confirm
yourself:

```powershell
curl https://scamshield-api.onrender.com/api/v1/health
```

Expected:

```json
{
  "status": "ok",
  "environment": "production",
  "model_available": true,
  "gemini_configured": true,
  "database_backend": "sqlite",
  "components": {"api": "ok", "database": "ok", "ml_model": "ok", "gemini": "configured"}
}
```

**Two things to check specifically:**

- `"model_available": true` → the `.joblib` reached the container. If it is
  `false`, Step 1b's `git ls-files` check failed; redo the export.
- `"gemini_configured": true` → your key was picked up.

### Step 2c — Prove a real scan works in the cloud

```powershell
curl -X POST https://scamshield-api.onrender.com/api/v1/scan/message `
  -H "Content-Type: application/json" `
  -H "X-API-Key: YOUR_API_KEY" `
  -d '{\"text\":\"Dear Customer, your SBI KYC is suspended. Update at http://sbi-kyc-verify.xyz/login within 24 hours.\",\"language\":\"en\"}'
```

Expect `"level": "critical"`, a non-zero `rule_engine.score`, an
`ml_prediction.spam_probability` around 0.9, and `"source": "gemini"` (if Gemini
is configured; `"fallback"` means the key did not take effect — check the Render
logs for a Gemini warning).

---

## Step 3 — Deploy the dashboard on Streamlit Cloud

1. Go to <https://share.streamlit.io> → **New app**
2. Repository: `<your-username>/scamshield-ai` · Branch: `main` · Main file path:
   **`frontend/app.py`**
3. **Advanced settings → Secrets**, paste exactly this (TOML format):

```toml
API_BASE_URL = "https://scamshield-api.onrender.com"
API_KEY = "the-same-long-random-string-from-step-2"
```

4. Click **Deploy**. First load takes 3–5 minutes.

### If the dashboard shows "Cannot reach the ScamShield API"

In order of likelihood:

1. **Render cold start (normal on free tier).** After 15 minutes idle the API
   sleeps and takes ~50 seconds to wake. Reload the page. This is not a bug.
2. **Wrong URL in secrets.** It must be `https://…onrender.com` with no trailing
   slash and no `/api/v1`.
3. **`API_KEY` mismatch.** If the API has a key set and the UI's differs, every
   call returns 401. They must match exactly.

---

## Step 4 — Final verification (run this from your machine)

```powershell
python scripts\prod_smoke_test.py --api https://scamshield-api.onrender.com --ui https://<you>-scamshield.streamlit.app --api-key YOUR_API_KEY
```

The 12 checks the earlier local run showed now run against the real public URLs.
Exit code `0` means production is genuinely working, `1` means something is wrong
— this is what you show in a viva instead of "it works on my laptop".

Then regenerate the evidence document against the live deployment:

```powershell
python scripts\capture_outputs.py --api https://scamshield-api.onrender.com --ui https://<you>-scamshield.streamlit.app
```

That rewrites `docs/OUTPUTS.md` with real cloud responses.

---

## Step 5 — Adding a real Gemini key later

Render → your service → **Environment** → edit `GEMINI_API_KEY` → **Save**.
Render redeploys automatically (~2 min). No code change is needed: the
explanation layer reads the key at runtime and falls back to templates when it is
missing, which is why the app never breaks without it.

---

## Step 6 — Updating the deployed app

```powershell
# in your normal project folder, after any code change
python scripts\export_for_git.py
cd dist\git-export
git add -A
git commit -m "Update: <what changed>"
git push
```

Render redeploys on every push (SQLite history is wiped on the free plan — Step 7
fixes that). Streamlit Cloud redeploys automatically too.

> **When you retrain the model**, the new `.joblib` files must reach the repo:
> re-run `export_for_git.py` (it force-includes them) and push. Otherwise the
> cloud keeps scoring with the old model while your laptop uses the new one.

---

## Step 7 — Making history survive redeploys (optional, still free-ish)

Render's free plan cannot attach disks, so this needs the **Starter** plan
(₹~600/month) — or simply accept that the free deployment starts with a fresh
history each deploy.

With a disk, two edits and you are done:

1. `render.yaml` — under the service, uncomment:

```yaml
    disk:
      name: scamshield-data
      mountPath: /app/data
      sizeGB: 1
```

2. Set the database path to that mount by adding to `envVars`:

```yaml
      - key: DATABASE_URL
        value: sqlite:////app/data/scamshield.db
```

The four slashes are correct: `sqlite://` + absolute path `/app/data/...`.
Alternatively delete the `DATABASE_URL` variable and set `DATA_DIR=/app/data` —
`backend/config.py` builds the URL from it and also treats a blank
`DATABASE_URL` as "not set" (there is a test for exactly that mistake).

**Do not use a disk on the free plan** — Render attaches it, the service fails to
start, and the error message does not say so clearly.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build fails: `COPY failed: models: not found` | Pushed your working folder instead of `dist/git-export` | Redo Step 1a |
| Deploy Live but `model_available: false` | `.joblib` files missing from the repo | `git ls-files \| Select-String joblib` |
| `401 Unauthorized` from the UI | `API_KEY` mismatch between Render and Streamlit secrets | Make them identical |
| UI: "Cannot reach the API" | Cold start, wrong URL, or trailing slash | Reload; check secrets |
| Every request slow first time (~50 s) | Render free tier sleeps after 15 min idle | Expected. Use `--api` smoke test to warm it before a demo |
| `gemini_configured: false` | Key not saved / typo / trailing space | Re-paste in Render → Environment |
| Dashboard empty after deploy | `SEED_DEMO_DATA` not applied, or history cleared | Set it to `true` and redeploy, or run one scan |
| Health check `database: fail` | `DATABASE_URL` malformed (e.g. disk not mounted) | Check for the four-slash SQLite form |

### Logs are your friend

Render → your service → **Logs**. The startup sequence should read:

```
Starting ScamShield AI v1.0.0 (production)
Database initialised at /app/data/scamshield.db
ML model ready: LogisticRegression
Predictor warm-up complete
Seeded 11 demo scan(s) via the real pipeline
Application startup complete.
```

If you see `Continuing without an ML model - rule-based detection only`, the
model artefact is missing from the image — that is the one line that matters.

---

## What was verified locally, and what was not

Being precise about this matters more than a green tick:

**Verified on this machine** (see `VERIFY.md`):

- The exact production code path: `ENVIRONMENT=production`, `DEBUG=false`,
  2 uvicorn workers, `PORT`-based binding, `DATA_DIR`-based database path,
  first-boot seeding (once, not duplicated across workers), `STORE_RAW_MESSAGE=false`.
- `docker build` semantics were **not** executed — there is no Docker daemon
  here. The Dockerfile was reviewed line by line and its two deployment-critical
  assumptions (`$PORT`, model artefacts in the build context) are covered by
  `tests/test_phase9_deploy.py`.
- Render/Streamlit Cloud builds themselves cannot be executed from here; they
  need your GitHub account. Steps 2b and 4 are the verification gates that catch
  anything the local run could not.

**Current test suite: 249 passed, 0 skipped** — including 12 deployment tests.
