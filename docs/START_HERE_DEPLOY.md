# Deploy ScamShield AI — complete runbook, start to finish

Written for **your** machine: Windows, project at
`C:\Users\Hp\OneDrive\Documents\ScamShield-AI`.

Follow the steps in order. Every step ends with a **✅ You should see** — if you
don't see it, stop and fix that step before continuing. Do not skip ahead; a
broken step 3 makes steps 4–9 fail with confusing errors.

Total time: **35–45 minutes**, of which ~15 is waiting for builds.

| Step | What | Time |
|---|---|---|
| 1 | Prerequisites | 10 min |
| 2 | Create the GitHub repo | 3 min |
| 3 | Create the Personal Access Token | 2 min |
| 4 | Prepare the export (train + build) | 5 min |
| 5 | Push to GitHub | 3 min |
| 6 | Verify what reached GitHub | 2 min |
| 7 | Deploy the API on Render | 10 min |
| 8 | Deploy the dashboard on Streamlit Cloud | 5 min |
| 9 | Verify the live deployment | 5 min |

---

## Step 1 — Prerequisites

### 1a. Open PowerShell (not cmd)

Press `Win`, type `powershell`, press Enter. The prompt starts with `PS C:\Users\Hp>`.
If it does not start with `PS`, you are in cmd.exe — close it and use PowerShell.

### 1b. Check Python and Git

```powershell
python --version
git --version
```

✅ **You should see** `Python 3.10.x` or higher, and `git version 2.x.x`.

If `python` opens the Microsoft Store or says "not recognized":
install from <https://www.python.org/downloads/> and **tick "Add python.exe to
PATH"** on the first installer screen. Then close and reopen PowerShell.

If `git` is not recognised: install from <https://git-scm.com/download/win>,
close and reopen PowerShell.

### 1c. Install the project dependencies

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"
python -m pip install -r requirements.txt
```

Takes 2–4 minutes. If it fails on `scikit-learn` or `scipy`, your Python is too new
or too old — use Python 3.11 or 3.12.

✅ **You should see** `Successfully installed ...` with no red `ERROR:` lines.

### 1d. Confirm the project itself works

```powershell
python -m pytest -q
```

✅ **You should see** `250 passed`.

> **If you see anything other than 250 passed, stop here.** Deploying a project
> that fails locally only moves the problem to a server you cannot debug as easily.

### 1e. Accounts you need

| Account | URL | Note |
|---|---|---|
| GitHub | github.com | Free |
| Render | render.com | Sign in **with GitHub** — no credit card |
| Streamlit Cloud | share.streamlit.io | Sign in **with GitHub** |
| Gemini API key *(optional)* | aistudio.google.com/apikey | Free tier; app works without it |

---

## Step 2 — Create the GitHub repository

1. Go to <https://github.com/new>
2. **Repository name:** `ScamShield-AI`
3. **Public** (needed for free Streamlit Cloud)
4. **Do NOT tick** "Add a README file", "Add .gitignore", or "Choose a license"

Those three tickboxes are the number one cause of a rejected push later — an
"empty" repo with a README is not empty, and Git will refuse the upload.

✅ **You should see** a page saying "Quick setup — if you've done this kind of
thing before" with a URL like
`https://github.com/Dhruva2004/ScamShield-AI.git`.

**Copy that URL exactly** — you need it in Step 5.

---

## Step 3 — Create a Personal Access Token

Git will ask for a password when you push. Your GitHub account password **will not
work** — GitHub removed password authentication in 2021.

1. GitHub → click your avatar → **Settings**
2. Bottom of the left sidebar → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)**
4. **Generate new token** → **Generate new token (classic)**
5. **Note:** `scamshield-deploy`
6. **Expiration:** 30 days
7. **Scopes:** tick **`repo`** (the whole top checkbox)
8. **Generate token**
9. **Copy the token now** — it starts with `ghp_` and is shown only once

Store it in a password manager. **Never** paste it into a chat, an issue, or a file
in the repo. If it leaks, delete it on this same page immediately.

✅ **You should see** a long string starting `ghp_...`.

> **Prefer not to make a token?** Run this once instead and Git will open a browser
> to authorise normally:
>
> ```powershell
> git config --global credential.helper manager
> ```
>
> Then in Step 5, a GitHub sign-in window appears instead of a password prompt.

---

## Step 4 — Prepare the deployable folder

### 4a. Why this step exists

Your trained model lives in `models/*.joblib`, and `.gitignore` excludes it —
correct for development, fatal for deployment. If those files never reach GitHub,
Render builds a working API **with no ML model**, and nothing shows an error.

The script below copies the project into `dist\git-export\` with exactly those
files force-included, and refuses to continue if anything is missing.

### 4b. Run it

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"
python scripts\export_for_git.py
```

✅ **You should see** all `OK` lines, ending with:

```
  OK    metrics.json                           3 model(s), chosen=LogisticRegression, F1=0.9407
  OK    Gemini optional                        app works with an empty GEMINI_API_KEY
  OK    no .env / secrets.toml                 clean

All preflight checks passed.

EXPORT
[export] 124 file(s) -> dist\git-export
[export]   included  models/model_logistic_regression.joblib
[export]   included  models/metrics.json
[export]   included  ml/vectorizers/tfidf_vectorizer.joblib
```

### 4c. If a line says FAIL

| FAIL line | Fix |
|---|---|
| `models/model_logistic_regression.joblib MISSING` | `python scripts\train_models.py` then re-run |
| `metrics.json MISSING` | same as above |
| `no .env / secrets.toml` shows a path | Delete that file from `dist\git-export` |
| `PermissionError: [WinError 5] Access is denied: ...\dist\git-export\.git\objects\...` | **Fixed in this version.** Git stores its objects read-only; older copies could not delete them. If you still see it: `Remove-Item -Recurse -Force dist` then re-run |

> **Why `dist\git-export\.git` is kept:** the export no longer deletes that folder,
> so your commit history and the `origin` remote survive rebuilds. An update is
> then just `git add -A && git commit -m "..." && git push`.

> **OneDrive note:** if the `dist` folder shows a cloud icon, its files may be
> online-only placeholders. Right-click the project folder → **Always keep on this
> device**.

---

## Step 5 — Push to GitHub

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI\dist\git-export"

git init
git config user.name  "Dhruva2004"
git config user.email "Dhruva2004@users.noreply.github.com"

git remote add origin https://github.com/Dhruva2004/ScamShield-AI.git
```

> Replace `Dhruva2004` in all three places with **your** GitHub username. Replace
> the URL with the one you copied in Step 2. Nothing in `<angle brackets>` should
> ever be typed literally — pasting a placeholder is what broke the earlier attempt.

```powershell
git branch -M main
git add -A
git commit -m "ScamShield AI - deployable snapshot"
git push -u origin main
```

When prompted:
- **Username:** your GitHub username
- **Password:** paste the `ghp_...` token (nothing appears as you paste — that is normal)

✅ **You should see** something like:

```
To https://github.com/Dhruva2004/ScamShield-AI.git
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

### If it fails

| Error | Cause | Fix |
|---|---|---|
| `remote origin already exists` | You ran `git remote add` twice | `git remote set-url origin <URL>` |
| `Authentication failed` | You typed your account password | Use the `ghp_` token |
| `Repository not found` | Repo missing, or username/URL wrong | Check `git remote get-url origin` |
| `! [rejected] ... (fetch first)` | The GitHub repo is not empty | `git push -u origin main --force` |
| `nothing to commit, working tree clean` | The export folder is empty | Re-run Step 4, check for ~124 files |
| `invalid refspec 'maincd ...'` | Two commands pasted as one | Type them on separate lines |

Full detail: `docs/PUSH_VERIFY.md`.

---

## Step 6 — Verify what actually reached GitHub

This is the step that decides whether your deployment has ML. Do not skip it.

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI\dist\git-export"

git fetch origin
git status -sb
git ls-tree -r --name-only origin/main | Select-String "\.joblib$"
```

✅ **You should see:**

```
## main...origin/main                                   <- no "[ahead N]"
ml/vectorizers/tfidf_vectorizer.joblib
models/model_logistic_regression.joblib
```

Two `.joblib` lines. Nothing else matters until you have them.

Two more checks:

```powershell
git ls-tree -r --name-only origin/main | Measure-Object -Line
#   -> Lines: 124   (far fewer = partial push)

git ls-tree -r --name-only origin/main | Select-String "^\.env$|\.db$|secrets\.toml"
#   -> must print NOTHING (no secrets, no local database)
```

---

## Step 7 — Deploy the API on Render

1. Go to <https://dashboard.render.com/blueprints>
2. **New Blueprint Instance**
3. Connect GitHub if asked, then choose `ScamShield-AI`
4. Render reads `render.yaml` and shows one service: **scamshield-api**
5. It asks for two environment variables — paste:

   | Key | Value |
   |---|---|
   | `GEMINI_API_KEY` | your key from aistudio.google.com/apikey (leave blank to deploy without Gemini) |
   | `API_KEY` | generate one: `python -c "import secrets;print(secrets.token_urlsafe(32))"` |

   **Save the `API_KEY` value** — Step 8 needs the identical string.
6. Click **Apply**

Build takes 5–10 minutes (it compiles scikit-learn). You can watch the log.

Everything else is already configured in `render.yaml`: `ENVIRONMENT=production`,
`DEBUG=false`, 2 workers, `STORE_RAW_MESSAGE=false` (no plaintext persistence), a
generated `PRIVACY_SALT`, and `SEED_DEMO_DATA=true` so the dashboard is not empty
on first load.

✅ **You should see** the service status go **Live**, and in the log:

```
Starting ScamShield AI v1.0.0 (production)
Database initialised at /app/data/scamshield.db
ML model ready: LogisticRegression
Predictor warm-up complete
Seeded 11 demo scan(s) via the real pipeline
Application startup complete.
```

**If you see `Continuing without an ML model - rule-based detection only`**, the
model files did not reach the repo — go back to Step 6.

### 7b. Test the API yourself

```powershell
curl https://scamshield-api.onrender.com/api/v1/health
```

✅ **You should see** `"status": "ok"`, `"model_available": true`, and
`"gemini_configured": true` (or `false` if you skipped the key — that is fine).

---

## Step 8 — Deploy the dashboard on Streamlit Cloud

1. Go to <https://share.streamlit.io> → **Create app**
2. **Repository:** `Dhruva2004/ScamShield-AI`
3. **Branch:** `main`
4. **Main file path:** `frontend/app.py`
5. Open **Advanced settings** → **Secrets** and paste exactly:

```toml
API_BASE_URL = "https://scamshield-api.onrender.com"
API_KEY = "the-same-value-you-pasted-in-render"
```

6. **Deploy**

✅ **You should see** the dashboard load with 11 demo scans, a risk distribution
chart, and a sidebar with six pages.

### If the Branch field says "This branch does not exist"

Streamlit fetches the branch list from GitHub at page load. That message means
GitHub has **no `main` branch** — i.e. the push in Step 5 did not complete.

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI\dist\git-export"
git status -sb
git branch -a
git ls-remote --heads origin
```

| `git ls-remote --heads origin` prints | Meaning | Fix |
|---|---|---|
| nothing at all | Nothing ever reached GitHub (repo still empty) | Redo Step 5 |
| `refs/heads/master` | Pushed under the old default name | `git branch -M main` then `git push -u origin main` |
| `refs/heads/main` | Branch does exist — the page is stale | Reload the Streamlit page (Ctrl+F5) and re-pick `main` |

Confirm in the browser too: open `https://github.com/<you>/<repo>` — if it shows the
"Quick setup" page with no file list, the repository is empty.

### If the dashboard shows an HTML 404 ("W3C//DTD HTML 3.2 Final")

That page is **not** from this API. FastAPI answers an unknown path with JSON
(`{"detail":"Not Found"}`); an HTML 404 means a different web server replied — a
hosting landing page, another app, or a wrong `API_BASE_URL`.

**The error message now prints the exact URL it called.** Read it, then:

1. Open `API_BASE_URL` + `/api/v1/health` in a browser. You must see JSON:
   `{"status":"ok", ...}`. If you see a website, the URL is wrong.
2. `API_BASE_URL` must be the **bare origin**: `https://your-api.onrender.com`
   — no `/api/v1`, no trailing slash.
3. If the URL is right and you still get HTML, the Render service is not running;
   check its log and status.

### If the dashboard says "Cannot reach the ScamShield API"

1. **Wait and reload.** Render's free tier sleeps after 15 minutes idle and takes
   ~50 seconds to wake. This is normal, not a bug.
2. Check `API_BASE_URL` has **no trailing slash** and **no** `/api/v1`.
3. Check `API_KEY` matches Render's exactly, character for character.

---

## Step 9 — Verify the whole deployment

From your machine:

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"
python scripts\prod_smoke_test.py --api https://scamshield-api.onrender.com --ui https://YOUR-APP.streamlit.app --api-key YOUR_API_KEY
```

(Replace `YOUR-APP` with your Streamlit app subdomain, and `YOUR_API_KEY` with the
value from Step 7.)

✅ **You should see** `12/12 checks passed` and `echo $LASTEXITCODE` → `0`.

Then regenerate the evidence document with real cloud responses — this is the
artefact you show in a report or viva:

```powershell
python scripts\capture_outputs.py --api https://scamshield-api.onrender.com --ui https://YOUR-APP.streamlit.app
```

It rewrites `docs/OUTPUTS.md`.

---

## Final checklist

- [ ] `pytest -q` → 250 passed, locally
- [ ] GitHub repo is public and contains both `.joblib` files
- [ ] No `.env`, no `.db`, no `secrets.toml` in the repo
- [ ] Render status **Live**; health says `model_available: true`
- [ ] Streamlit app loads and shows scan history
- [ ] `prod_smoke_test.py` → 12/12, exit code 0
- [ ] `docs/OUTPUTS.md` regenerated against the live URLs
- [ ] Token revoked or stored in a password manager, never in the repo

---

## What is free, and what is not

| Piece | Plan | Limits |
|---|---|---|
| GitHub repo | Free | Public repo, unlimited |
| Render web service (Docker) | Free | 750 h/month; **sleeps after 15 min idle** (~50 s cold start) |
| Streamlit Community Cloud | Free | 1 GB RAM, public app |
| Gemini API | Free tier | Rate-limited |

**History does not survive redeploys on the free plan.** Render's free tier has no
persistent disk, so the SQLite file is wiped on each deploy. The app handles this
by design — it recreates the schema and reseeds demo data, so you get a fresh
history, never a broken site. Persistent history requires Render Starter (~₹600/month)
plus a disk; see `docs/DEPLOY_RENDER.md` Step 7.

**Do not attach a disk on the free plan** — the service fails to start and the
error does not explain why.

---

## Updating after a code change

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"
python scripts\export_for_git.py

cd "dist\git-export"
git add -A
git commit -m "describe what changed"
git push
```

Render redeploys automatically on every push. If you retrained the model, the new
`.joblib` must be re-exported (Step 4) or the cloud keeps scoring with the old one.

---

## Honest status of each piece

| Verified on a machine | Written and reviewed only |
|---|---|
| The app: 250 tests, 79% coverage, production profile, 12/12 smoke test, load test | `Dockerfile.api` / `.ui` and `docker-compose.yml` — **no Docker** in the build sandbox |
| `PORT` / `DATA_DIR` / seeding behaviour (12 dedicated tests) | `nginx.conf`, both systemd units — no nginx or systemd available here |
| The export script and the git sequence (reproduced end-to-end) | Render and Streamlit builds — these require your accounts |

Step 9 is where those gaps get closed. Run it; if it returns 12/12, the deployment
genuinely works, and you have evidence that isn't "it worked on my laptop".
