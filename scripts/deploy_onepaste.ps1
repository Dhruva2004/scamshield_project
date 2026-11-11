
# ============================================================================
#  ScamShield AI - ONE-PASTE deploy preparation
#  Copy everything below the line into PowerShell and press Enter.
#  It asks for your GitHub username/repo, so there is nothing to edit by hand.
# ============================================================================
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Hp\OneDrive\Documents\ScamShield-AI"

$GitHubUser = Read-Host "GitHub username [Dhruva2004]"
if ([string]::IsNullOrWhiteSpace($GitHubUser)) { $GitHubUser = "Dhruva2004" }
$RepoName = Read-Host "Repository name [ScamShield-AI]"
if ([string]::IsNullOrWhiteSpace($RepoName)) { $RepoName = "ScamShield-AI" }
$RemoteUrl = "https://github.com/$GitHubUser/$RepoName.git"
Write-Host "`nTarget repo: $RemoteUrl" -ForegroundColor Cyan
Write-Host "Make sure this repo EXISTS and is EMPTY (no README) before continuing.`n"

# ---- 1. build the Git-ready export ----------------------------------------
python scripts\export_for_git.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nEXPORT FAILED - fix the FAIL lines above, then run this again." -ForegroundColor Red
    return
}

# ---- 2. verify the export before trusting it ------------------------------
$export = Join-Path (Get-Location).Path "dist\git-export"
$required = @("models\model_logistic_regression.joblib",
              "ml\vectorizers\tfidf_vectorizer.joblib",
              "models\metrics.json", "render.yaml", "deploy\Dockerfile.api")
foreach ($rel in $required) {
    if (Test-Path (Join-Path $export $rel)) { Write-Host "  OK   $rel" -ForegroundColor Green }
    else { Write-Host "  MISSING $rel - stopping." -ForegroundColor Red; return }
}
$count = (Get-ChildItem $export -Recurse -File -Force |
          Where-Object { $_.FullName -notmatch '\\\.git\\' }).Count
Write-Host "  export file count: $count"
if ($count -lt 50) { Write-Host "Export is too small ($count) - re-run step 1." -ForegroundColor Red; return }
$leak = Get-ChildItem $export -Recurse -Force -Include ".env","secrets.toml" -ErrorAction SilentlyContinue
if ($leak) { Write-Host "SECRET FILE IN EXPORT - stopping." -ForegroundColor Red; return }

# ---- 3. git: repo, identity, remote --------------------------------------
Set-Location $export
if (-not (Test-Path ".git")) { git init | Out-Null }
if (-not (git config user.name))  { git config user.name  $GitHubUser }
if (-not (git config user.email)) { git config user.email "$GitHubUser@users.noreply.github.com" }
if ((git remote) -contains "origin") { git remote set-url origin $RemoteUrl }
else { git remote add origin $RemoteUrl }
Write-Host "  origin -> $(git remote get-url origin)"

git branch -M main
git add -A
$null = git rev-parse --verify HEAD 2>$null
if ($LASTEXITCODE -ne 0) {
    git commit -m "ScamShield AI - deployable snapshot"
} elseif (git status --porcelain) {
    git commit -m "ScamShield AI - update"
}

# ---- 4. the check that decides whether the deployment has ML -------------
$inCommit = git ls-tree -r --name-only HEAD | Select-String "\.joblib$"
if (-not $inCommit) {
    Write-Host "`nThe commit does NOT contain the model files - stopping." -ForegroundColor Red
    return
}
Write-Host "`n  in commit:" -ForegroundColor Green
$inCommit | ForEach-Object { Write-Host "    $_" -ForegroundColor Green }

# ---- 5. push -------------------------------------------------------------
Write-Host "`nPushing... (password = Personal Access Token, not your account password)" -ForegroundColor Cyan
git push -u origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nPUSHED." -ForegroundColor Green
    Write-Host "Next: render.com -> New -> Blueprint Instance -> pick '$RepoName'" -ForegroundColor Cyan
    Write-Host "Paste GEMINI_API_KEY + API_KEY, then Apply." -ForegroundColor Cyan
} else {
    Write-Host "`nPush failed - read the line above." -ForegroundColor Red
    Write-Host "  'Repository not found'      -> repo missing, or username/name wrong"
    Write-Host "  'Authentication failed'     -> use a Personal Access Token"
    Write-Host "  'Updates were rejected'     -> repo is not empty; delete it or:"
    Write-Host "                                 git push -u origin main --force"
}
