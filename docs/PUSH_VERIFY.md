# How to know if your push actually worked

A push can fail in six different ways, and three of them print something that
looks like success. This page gives you one command that answers the question,
plus how to read each failure.

---

## 0. The 10-second answer

```powershell
cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI\dist\git-export"

git fetch origin
git status -sb
git ls-remote --heads origin
```

Read it like this:

| What you see | Meaning |
|---|---|
| `## main...origin/main` with **no** `[ahead N]` | ✅ **Pushed.** Local and remote are identical |
| `## main...origin/main [ahead 3]` | ❌ Not pushed — 3 commits waiting |
| `## main...origin/main [ahead 1, behind 4]` | ❌ Rejected/diverged — someone else pushed |
| `## main` with no `origin/main` at all | ❌ Never pushed successfully |
| `git ls-remote` prints a SHA + `refs/heads/main` | ✅ The branch exists on GitHub |
| `git ls-remote` prints nothing | ❌ Nothing is on GitHub |

That is the whole check. Everything below is detail.

---

## 1. The definitive test: is the model in the cloud?

A push that "succeeds" can still have shipped a repository with no ML model.
After pushing, confirm the two artefacts are visible **on GitHub**, not just on
your disk:

```powershell
git ls-tree -r --name-only origin/main | Select-String "\.joblib$"
```

Must print **both**:

```
ml/vectorizers/tfidf_vectorizer.joblib
models/model_logistic_regression.joblib
```

Or verify in the browser — `https://github.com/<you>/<repo>/tree/main/models`
should list `model_logistic_regression.joblib` (164 KB).

If it is missing, Render will still start, health will say
`"model_available": false`, and the app runs rules-only. No error is raised. This
check is the only thing that catches it.

---

## 2. Exit codes (for scripting)

```powershell
git push -u origin main
if ($LASTEXITCODE -eq 0) { "PUSHED" } else { "FAILED - code $LASTEXITCODE" }
```

- `0` = every ref was accepted
- `1` = at least one ref was rejected, or auth/network failed

**`git push` returning 0 is necessary but not sufficient** — it only means GitHub
accepted the refs. Step 1 above proves the contents are right.

---

## 3. Every failure mode, and how to tell them apart

### A. Authentication failed (401)

```
remote: Support for password authentication was removed
fatal: Authentication failed for 'https://github.com/...'
```

You typed your **account password**. GitHub needs a Personal Access Token.
Fix: create one (Settings → Developer settings → Personal access tokens →
Tokens (classic) → scope `repo`) and paste it as the password.

Do not put the token in the remote URL — it is stored in plain text in
`.git/config`, and that file is excluded from workspace snapshots for this
reason. Use Git Credential Manager, which stores it in Windows Credential Manager.

### B. Repository not found (404)

```
remote: Repository not found.
fatal: repository 'https://github.com/you/repo.git' not found
```

Three causes, in order of likelihood:

1. The repo does not exist on GitHub yet — create it.
2. Username or repo name is misspelled. Check with:
   `git remote get-url origin`
3. A token was used that lacks `repo` scope, so a **private** repo looks like a
   missing one.

Note: GitHub returns 404 (not 403) for private repos you cannot access, so
"not found" can also mean "no permission".

### C. Non-fast-forward rejection (`! [rejected]`)

```
 ! [rejected]        main -> main (fetch first)
error: failed to push some refs to '...'
hint: Updates were rejected because the remote contains work that you do not
hint: have locally.
```

The GitHub repo is **not empty** — it has a README, a .gitignore, or a licence
file created with the repo. Two fixes:

```powershell
# Option 1 (safe, keeps their history): merge then push
git pull --rebase origin main
git push -u origin main

# Option 2 (this is a fresh deploy snapshot, so overwrite is legitimate)
git push -u origin main --force
```

Use `--force` only on this throwaway export directory, never on a repo with
other people's work.

### D. Protected branch rejection

```
remote: error: GH006: Protected branch update failed
```

The branch has protection rules (required reviews, or "require status checks").
Fix: Settings → Branches → edit the rule, or push to a new branch and open a PR.

### E. File size rejection

```
remote: error: File models/model_logistic_regression.joblib is 165.43 MB;
remote: exceeds GitHub's file size limit of 100.00 MB
```

Cannot happen here — the largest file is 468 KB (`SMSSpamCollection`). If you ever
see it, you are pushing the wrong folder (e.g. a stray dataset or a virtualenv).

### F. "Everything up-to-date" but the files are wrong

```
Everything up-to-date
```

Nothing was committed since the last push. Usually this means the export was
rebuilt but never committed, or you are in the wrong directory:

```powershell
git status
git log --oneline -3
```

This is the trap you already hit: **in a repository with no commits,
`git status` also reports "working tree clean"**. Never trust "clean" — ask for
the commit:

```powershell
git rev-parse --verify HEAD        # fails => there is no commit at all
git ls-tree -r --name-only HEAD    # what is actually in that commit
```

---

## 4. What "successfully pushed" does NOT prove

| Looks like success | Still unverified |
|---|---|
| `git push` exit code 0 | whether the model files are in the commit → step 1 |
| Branch visible on GitHub | whether Render built it → check its build log |
| Render says **Live** | whether the ML layer loaded → `curl .../api/v1/health` → `model_available` |
| Health says `ok` | whether scans actually work → run `scripts/prod_smoke_test.py` |

Deployment confidence comes from the last line, not the first.

---

## 5. Full post-push checklist

```powershell
# 1. committed and pushed?
git fetch origin; git status -sb

# 2. model files in the remote?
git ls-tree -r --name-only origin/main | Select-String "\.joblib$"

# 3. only expected files? (no secrets, no database)
git ls-tree -r --name-only origin/main | Select-String "^\.env$|\.db$|secrets\.toml"
#    -> must print NOTHING

# 4. how many files?
git ls-tree -r --name-only origin/main | Measure-Object -Line
#    -> ~124 for a full export; far fewer means a partial push

# 5. is the app live?
curl https://scamshield-api.onrender.com/api/v1/health
#    -> "model_available": true, "gemini_configured": true

# 6. does it actually work?
python scripts\prod_smoke_test.py --api https://scamshield-api.onrender.com --ui https://YOUR-APP.streamlit.app --api-key YOUR_API_KEY
#    -> 12/12, exit code 0
```

---

## 6. Token hygiene

- A Personal Access Token is a **password**. Anyone holding it can read and write
  every repo it is scoped to.
- **Never paste a token into a chat, an issue, a screenshot, or a file in the
  repo.** If it has been exposed anywhere — including a transcript or a
  screenshot — treat it as compromised and revoke it immediately:
  GitHub → Settings → Developer settings → Personal access tokens → **Delete**.
- Prefer **fine-grained tokens** scoped to one repository with `Contents:
  Read and write`, and set an expiry (30 days is plenty for a project deploy).
- Set credentials once and let Windows Credential Manager hold them:

```powershell
git config --global credential.helper manager
```

Then the first `git push` prompts once and remembers — no token in any command,
no token in `.git/config`.

- If a token ever does end up in a file inside the repo, revoking it is not
  enough — the value stays in Git history. Rotate the token and, if it was
  pushed, rewrite history or start a fresh repository.
