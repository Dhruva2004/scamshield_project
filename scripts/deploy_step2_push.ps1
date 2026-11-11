
# ============================================================================
#  ScamShield AI - Step 2: push the export to GitHub (safe to re-run)
#  ---------------------------------------------------------------------------
#  Run in PowerShell from ANY folder:
#
#      cd "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"
#      powershell -ExecutionPolicy Bypass -File .\scripts\deploy_step2_push.ps1
#
#  It fixes the four things that went wrong in your first attempt:
#    1. `origin` pointed at the literal placeholder YOUR-USERNAME  -> set-url
#    2. no commit / wrong branch                                    -> commit if needed
#    3. pushes to the wrong refspec                                 -> explicit main
#    4. a repo nested inside another git repo (OneDrive + docs)     -> detected
#
#  Before the first run, create an EMPTY repo on GitHub (no README) and edit
#  the two variables below.
# ============================================================================

$ErrorActionPreference = "Stop"

# -- EDIT THESE TWO LINES ----------------------------------------------------
$GitHubUser = "Dhruva2004"
$RepoName   = "ScamShield-AI"
# ---------------------------------------------------------------------------

$ProjectRoot = Join-Path (Get-Location).Path ""
$ExportDir   = Join-Path $ProjectRoot "dist\git-export"
$RemoteUrl   = "https://github.com/$GitHubUser/$RepoName.git"

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host " Step 2 - push the export to GitHub" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host " Target repo: $RemoteUrl"

# --- 1. Do we have the export? ---------------------------------------------
Write-Host "`n[1/7] Checking the export folder" -ForegroundColor Yellow
if (-not (Test-Path $ExportDir)) {
    Write-Host "`n[STOP] $ExportDir does not exist." -ForegroundColor Red
    Write-Host "       Run Step 1 first:" -ForegroundColor Red
    Write-Host "       powershell -ExecutionPolicy Bypass -File .\scripts\deploy_step1_prepare.ps1" -ForegroundColor Red
    exit 1
}
Set-Location $ExportDir
Write-Host "      OK - $ExportDir" -ForegroundColor Green

# --- 2. THE critical file check --------------------------------------------
Write-Host "`n[2/7] CRITICAL - trained model files in the export" -ForegroundColor Yellow
$required = @(
    "models\model_logistic_regression.joblib",
    "ml\vectorizers\tfidf_vectorizer.joblib",
    "render.yaml",
    "deploy\Dockerfile.api"
)
$missing = @()
foreach ($rel in $required) {
    if (Test-Path (Join-Path $ExportDir $rel)) {
        Write-Host "      OK   $rel" -ForegroundColor Green
    } else {
        Write-Host "      FAIL $rel" -ForegroundColor Red
        $missing += $rel
    }
}
if ($missing.Count -gt 0) {
    Write-Host "`n[STOP] Export is incomplete. Re-run Step 1, then this script." -ForegroundColor Red
    exit 1
}

# --- 2b. Is the export actually populated? --------------------------------
# An empty folder produces a repo where `git status` reports "clean" and there is
# nothing to commit - which looks like success and pushes an empty repository.
$fileCount = (Get-ChildItem -Path $ExportDir -Recurse -File -Force |
              Where-Object { $_.FullName -notmatch "\\\.git\\" }).Count
Write-Host "`n[2b/7] Export contents: $fileCount file(s)"
if ($fileCount -lt 50) {
    Write-Host "`n[STOP] Only $fileCount files - the export is empty or incomplete." -ForegroundColor Red
    Write-Host "       A full export has ~120 files. Re-run Step 1." -ForegroundColor Red
    exit 1
}
Write-Host "      OK - looks like a full export" -ForegroundColor Green

# --- 3. No secrets ---------------------------------------------------------
Write-Host "`n[3/7] Secrets check" -ForegroundColor Yellow
$leaked = Get-ChildItem -Path $ExportDir -Recurse -Force -Include ".env","secrets.toml" -ErrorAction SilentlyContinue
if ($leaked) {
    Write-Host "`n[STOP] A secrets file is inside the export:" -ForegroundColor Red
    $leaked | ForEach-Object { Write-Host "       $($_.FullName)" -ForegroundColor Red }
    Write-Host "       Delete it before pushing. Never commit .env." -ForegroundColor Red
    exit 1
}
Write-Host "      OK - no .env / secrets.toml" -ForegroundColor Green

# --- 4. Correct repo, correct but-not-nested git ---------------------------
Write-Host "`n[4/7] Git repository" -ForegroundColor Yellow
if (-not (Test-Path (Join-Path $ExportDir ".git"))) {
    git init | Out-Null
    Write-Host "      initialised a new repository" -ForegroundColor Gray
}
$topLevel = (git rev-parse --show-toplevel 2>$null)
if ($topLevel -and ($topLevel.TrimEnd("\") -ne $ExportDir.TrimEnd("\"))) {
    Write-Host "`n[WARNING] This repo is nested inside another one:" -ForegroundColor Yellow
    Write-Host "          git root : $topLevel" -ForegroundColor Yellow
    Write-Host "          expected : $ExportDir" -ForegroundColor Yellow
    Write-Host "          That usually means an earlier 'git init' in the PROJECT root." -ForegroundColor Yellow
    Write-Host "          If 'git status' below shows extra files, say so and I will fix it." -ForegroundColor Yellow
}
# Identity: git refuses to commit without it.
$userName  = (git config user.name 2>$null)
$userEmail = (git config user.email 2>$null)
if (-not $userName)  { git config user.name  $GitHubUser; Write-Host "      set user.name = $GitHubUser" -ForegroundColor Gray }
if (-not $userEmail) { git config user.email "$GitHubUser@users.noreply.github.com"; Write-Host "      set user.email = $GitHubUser@users.noreply.github.com" -ForegroundColor Gray }
Write-Host "      OK - git repository ready" -ForegroundColor Green

# --- 5. Fix the remote (this is what broke your first attempt) -------------
Write-Host "`n[5/7] Remote 'origin'" -ForegroundColor Yellow
$existing = (git remote 2>$null)
if ($existing -contains "origin") {
    $current = (git remote get-url origin)
    Write-Host "      was: $current"
    git remote set-url origin $RemoteUrl
    Write-Host "      now: $RemoteUrl" -ForegroundColor Gray
} else {
    git remote add origin $RemoteUrl
    Write-Host "      added: $RemoteUrl" -ForegroundColor Gray
}
Write-Host "      OK" -ForegroundColor Green

# --- 6. Branch + commit ----------------------------------------------------
Write-Host "`n[6/7] Branch and commit" -ForegroundColor Yellow
git branch -M main 2>$null
git add -A
$pending = (git status --porcelain)
if ($pending) {
    git commit -m "ScamShield AI - deployable snapshot" | Out-Null
    Write-Host "      committed pending changes" -ForegroundColor Gray
} else {
    Write-Host "      nothing pending - the previous commit will be used" -ForegroundColor Gray
}

# "Working tree clean" is NOT proof a commit exists: in a repo with no commits,
# git status also reports clean. Ask git directly.
$hasCommit = $false
git rev-parse --verify HEAD 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { $hasCommit = $true }

if (-not $hasCommit) {
    Write-Host "`n[STOP] There is no commit in this repository." -ForegroundColor Red
    Write-Host "       The export was empty when git last ran, so nothing was staged." -ForegroundColor Red
    Write-Host "       Fix: re-run Step 1, then run this script again." -ForegroundColor Red
    exit 1
}
Write-Host "      OK - commit exists ($(git rev-parse --short HEAD))" -ForegroundColor Green

# The commit must contain the model files. Verify in HEAD, not just on disk.
$inHead = (git ls-tree -r --name-only HEAD 2>$null | Select-String "\.joblib$")
if (-not $inHead) {
    Write-Host "`n[STOP] The current commit does NOT contain the .joblib files." -ForegroundColor Red
    Write-Host "       Re-run Step 1, then run this script again." -ForegroundColor Red
    exit 1
}
Write-Host "      OK - commit contains:" -ForegroundColor Green
$inHead | ForEach-Object { Write-Host "           $($_.ToString())" -ForegroundColor Green }

# --- 7. Push ---------------------------------------------------------------
Write-Host "`n[7/7] Push to GitHub" -ForegroundColor Yellow
Write-Host "      If prompted for a password: use a Personal Access Token, not your"
Write-Host "      account password. github.com -> Settings -> Developer settings ->"
Write-Host "      Personal access tokens -> Tokens (classic) -> tick 'repo'."
Write-Host ""

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[FAILED] Read the error line above. Common causes:" -ForegroundColor Red
    Write-Host "  * 'Repository not found'  -> the repo does not exist yet, or the" -ForegroundColor Red
    Write-Host "                               username/name above is wrong." -ForegroundColor Red
    Write-Host "  * 'Authentication failed' -> use a Personal Access Token." -ForegroundColor Red
    Write-Host "  * 'Updates were rejected'-> the GitHub repo already has files." -ForegroundColor Red
    Write-Host "                               Create an EMPTY repo, then re-run, or run:" -ForegroundColor Red
    Write-Host "                               git push -u origin main --force" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host " PUSHED - now prove what actually landed" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Open this in your browser to confirm the files are there:" -ForegroundColor Cyan
Write-Host "   $RemoteUrl" -ForegroundColor White
Write-Host "   ...then navigate to models/ and ml/vectorizers/ and check both .joblib files" -ForegroundColor White
Write-Host ""
Write-Host " Next: Render -> Dashboard -> New -> Blueprint Instance -> pick '$RepoName'" -ForegroundColor Cyan
Write-Host " Then paste GEMINI_API_KEY and API_KEY, and click Apply." -ForegroundColor Cyan
Write-Host ""
