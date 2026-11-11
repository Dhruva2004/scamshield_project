
# ============================================================================
#  ScamShield AI - Step 1: build the Git-ready folder
#  ---------------------------------------------------------------------------
#  Run this from PowerShell (NOT cmd.exe):
#
#      cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"
#      powershell -ExecutionPolicy Bypass -File .\scripts\deploy_step1_prepare.ps1
#
#  If PowerShell blocks scripts on your machine, the -ExecutionPolicy Bypass
#  above is the fix. It applies only to this one run; nothing is changed
#  system-wide.
#
#  The quoted path matters: this folder path contains a space, and an unquoted
#  "cd C:\Users\Hp\OneDrive\Documents\ScamShield-AI\" would fail.
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host " ScamShield AI - prepare for free deployment (Render + GitHub)" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan

# --- 0. Where are we? -------------------------------------------------------
$ProjectRoot = (Get-Location).Path
Write-Host "`n[1/6] Project folder" -ForegroundColor Yellow
Write-Host "      $ProjectRoot"

if (-not (Test-Path (Join-Path $ProjectRoot "backend\main.py"))) {
    Write-Host "`n[STOP] backend\main.py not found." -ForegroundColor Red
    Write-Host "       You are in the wrong folder. Run:" -ForegroundColor Red
    Write-Host '       cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"' -ForegroundColor Red
    exit 1
}
Write-Host "      OK - project root detected" -ForegroundColor Green

# --- 1. Python available? ---------------------------------------------------
Write-Host "`n[2/6] Python" -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "      $pyVersion"
} catch {
    Write-Host "`n[STOP] 'python' is not on PATH." -ForegroundColor Red
    Write-Host "       Install Python 3.10+ from python.org and tick 'Add python.exe to PATH'." -ForegroundColor Red
    exit 1
}

# --- 2. Dependencies (only what the preflight needs) ------------------------
Write-Host "`n[3/6] Checking dependencies" -ForegroundColor Yellow
$deps = python -c "import fastapi, sklearn, joblib, pydantic_settings; print('ok')" 2>&1
if ($deps -notmatch "ok") {
    Write-Host "      Missing packages. Installing from requirements.txt (2-4 min)..." -ForegroundColor Yellow
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n[STOP] pip install failed. Read the error above." -ForegroundColor Red
        exit 1
    }
}
Write-Host "      OK - fastapi, scikit-learn, joblib, pydantic-settings present" -ForegroundColor Green

# --- 3. Model artefacts -----------------------------------------------------
Write-Host "`n[4/6] Trained model artefacts" -ForegroundColor Yellow
$modelFile = Join-Path $ProjectRoot "models\model_logistic_regression.joblib"
$vecFile   = Join-Path $ProjectRoot "ml\vectorizers\tfidf_vectorizer.joblib"

if (-not (Test-Path $modelFile)) {
    Write-Host "      Model missing - training now (takes ~1 min)..." -ForegroundColor Yellow
    python scripts\train_models.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n[STOP] Training failed. Read the error above." -ForegroundColor Red
        exit 1
    }
}
Write-Host "      OK - model + vectorizer present" -ForegroundColor Green

# --- 4. Build the Git-ready export -----------------------------------------
Write-Host "`n[5/6] Building the Git-ready folder (dist\git-export)" -ForegroundColor Yellow
Write-Host "      This folder force-includes the .joblib files that .gitignore excludes."
python scripts\export_for_git.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[STOP] Preflight failed. Fix the FAIL lines above, then re-run." -ForegroundColor Red
    exit 1
}

# --- 5. Verify the two files that decide success or silent failure ----------
Write-Host "`n[6/6] CRITICAL CHECK - are the model files in the export?" -ForegroundColor Yellow
$exportDir = Join-Path $ProjectRoot "dist\git-export"
$checks = @(
    "models\model_logistic_regression.joblib",
    "ml\vectorizers\tfidf_vectorizer.joblib",
    "models\metrics.json",
    "render.yaml",
    "deploy\Dockerfile.api",
    "frontend\app.py"
)
$allGood = $true
foreach ($rel in $checks) {
    if (Test-Path (Join-Path $exportDir $rel)) {
        Write-Host "      OK   $rel" -ForegroundColor Green
    } else {
        Write-Host "      FAIL $rel" -ForegroundColor Red
        $allGood = $false
    }
}

if (-not $allGood) {
    Write-Host "`n[STOP] The export is incomplete. Do NOT deploy it." -ForegroundColor Red
    exit 1
}

# --- 6. Make sure no secrets are in the export ------------------------------
$leaked = Get-ChildItem -Path $exportDir -Recurse -Force -Include ".env","secrets.toml" -ErrorAction SilentlyContinue
if ($leaked) {
    Write-Host "`n[STOP] A secrets file ended up in the export:" -ForegroundColor Red
    $leaked | ForEach-Object { Write-Host "       $($_.FullName)" -ForegroundColor Red }
    exit 1
}
Write-Host "      OK   no .env / secrets.toml in the export" -ForegroundColor Green

# --- 7. Git availability ----------------------------------------------------
Write-Host ""
try {
    $gitVersion = git --version 2>&1
    Write-Host "Git: $gitVersion" -ForegroundColor Gray
} catch {
    Write-Host "`n[WARNING] 'git' is not on PATH." -ForegroundColor Yellow
    Write-Host "          Install Git from https://git-scm.com/download/win, then re-open PowerShell." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host " STEP 1 COMPLETE - the export is ready." -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next: push it to GitHub." -ForegroundColor Cyan
Write-Host ""
Write-Host " EASIER: run the automated version instead of copy-pasting git commands -" -ForegroundColor Cyan
Write-Host " it fills in your username, fixes the remote and pushes in one go:" -ForegroundColor Cyan
Write-Host "   powershell -ExecutionPolicy Bypass -File .\scripts\deploy_step2_push.ps1" -ForegroundColor White
Write-Host ""
Write-Host " Manual route (anything in <angle brackets> MUST be replaced):" -ForegroundColor Cyan
Write-Host ""
Write-Host '  cd "dist\git-export"' -ForegroundColor White
Write-Host '  git init' -ForegroundColor White
Write-Host '  git add -A' -ForegroundColor White
Write-Host '  git commit -m "ScamShield AI - deployable snapshot"' -ForegroundColor White
Write-Host '  git branch -M main' -ForegroundColor White
Write-Host '  # Replace both <...> placeholders with YOUR values before running:' -ForegroundColor Yellow
Write-Host '  git remote add origin https://github.com/<your-github-username>/<your-repo>.git' -ForegroundColor White
Write-Host '  git push -u origin main' -ForegroundColor White
Write-Host ""
Write-Host " Then PROVE the model files were pushed (must list 2 .joblib files):" -ForegroundColor Cyan
Write-Host ""
Write-Host '  git ls-files | Select-String joblib' -ForegroundColor White
Write-Host ""
Write-Host " If Git asks for a password: GitHub needs a Personal Access Token," -ForegroundColor Yellow
Write-Host " not your account password. Create one at:" -ForegroundColor Yellow
Write-Host "   GitHub -> Settings -> Developer settings -> Personal access tokens" -ForegroundColor Yellow
Write-Host "   -> Tokens (classic) -> Generate new token -> tick 'repo' scope" -ForegroundColor Yellow
Write-Host "   Use the token as the password when Git prompts you." -ForegroundColor Yellow
Write-Host ""
Write-Host " Also worth signing in once instead: run 'git config --global user.name'"
Write-Host " and 'git config --global user.email' if Git complains about identity."
Write-Host ""
