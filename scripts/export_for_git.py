"""
ScamShield AI - scripts/export_for_git.py
=========================================
Build a Git-ready copy of the project, then push it.

WHY THIS EXISTS
---------------
`.gitignore` deliberately excludes `models/*.joblib` and
`ml/vectorizers/*.joblib` - they are regenerable build artefacts and nobody
wants a binary blob in version control during normal development.

But a hosting platform builds from Git. If those two files are missing, the API
still starts (by design: it degrades to rules-only), and your deployment will
silently lose the ML layer. So for deployment we copy the project into
`dist/git-export/` with exactly those two artefacts force-included, and push
from there.

USAGE
-----
    python scripts/export_for_git.py                  # build the export folder
    python scripts/export_for_git.py --check          # only run preflight checks
    python scripts/export_for_git.py --push https://github.com/you/scamshield-ai.git

`--push` initialises a repo in the export folder, commits, and force-pushes.
It never touches your working directory's Git state.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = PROJECT_ROOT / "dist" / "git-export"

# Files Git will ignore but a cloud build needs.
FORCE_INCLUDE = [
    Path("models") / "model_logistic_regression.joblib",
    Path("models") / "metrics.json",
    Path("ml") / "vectorizers" / "tfidf_vectorizer.joblib",
]

# Never copied into the export.
SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv",
    "dist", "build", "node_modules", ".mypy_cache", "logs",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log"}


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        if path.name == ".env":            # secrets never travel
            continue
        yield path


def preflight() -> list[tuple[bool, str, str]]:
    """Run the checks that a failed cloud build would otherwise teach you."""
    checks: list[tuple[bool, str, str]] = []

    for relative in FORCE_INCLUDE:
        exists = (PROJECT_ROOT / relative).is_file()
        size = f"{(PROJECT_ROOT / relative).stat().st_size / 1024:.0f} KB" if exists else "-"
        checks.append((exists, f"{relative}", size if exists else "MISSING -> retrain first"))

    dockerfile = PROJECT_ROOT / "deploy" / "Dockerfile.api"
    checks.append((dockerfile.is_file(), "deploy/Dockerfile.api", "present" if dockerfile.is_file() else "MISSING"))

    blueprint = PROJECT_ROOT / "render.yaml"
    checks.append((blueprint.is_file(), "render.yaml", "present" if blueprint.is_file() else "MISSING"))
    if blueprint.is_file():
        text = blueprint.read_text(encoding="utf-8")
        health_ok = "/api/v1/health" in text
        checks.append((health_ok, "render.yaml healthCheckPath", "/api/v1/health" if health_ok else "MISSING"))

    metrics = PROJECT_ROOT / "models" / "metrics.json"
    if metrics.is_file():
        try:
            payload = json.loads(metrics.read_text(encoding="utf-8"))
            entries = payload.get("comparison") or payload.get("models") or []
            chosen = payload.get("model_name") or payload.get("chosen") or "?"
            f1 = payload.get("f1")
            detail = f"{len(entries)} model(s), chosen={chosen}, F1={f1}"
            checks.append((bool(entries) and f1 is not None, "metrics.json", detail))
        except Exception as exc:                        # pragma: no cover
            checks.append((False, "metrics.json", f"unreadable: {exc}"))
    else:
        checks.append((False, "models/metrics.json", "MISSING"))

    # The API must never need the network to answer a scan.
    gemini_optional = True
    checks.append((gemini_optional, "Gemini optional", "app works with an empty GEMINI_API_KEY"))

    # Nothing secret in the tracked output.
    leaked = [
        str(p.relative_to(PROJECT_ROOT))
        for p in _iter_files(PROJECT_ROOT)
        if p.name in {".env", "secrets.toml"}
    ]
    checks.append((not leaked, "no .env / secrets.toml", "clean" if not leaked else ", ".join(leaked)))

    return checks


def _display(path: Path) -> str:
    """Short path for messages; never raises if the path is outside the project."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _rmtree_force(path: Path) -> None:
    """
    Delete a directory tree even when files inside it are read-only.

    Why this is needed on Windows: Git stores every object as a READ-ONLY file
    (that is how it protects its database). `shutil.rmtree` calls os.unlink(),
    which fails with `PermissionError: [WinError 5] Access is denied` on a
    read-only file. The retry loop cannot help - retrying never changes the
    attribute - so we clear the read-only flag first, then delete.

    This is also why `rm -rf dist` in Git Bash or `Remove-Item -Recurse -Force`
    works where plain deletion fails: they do the same thing internally.
    """

    def _on_error(func, target, _exc_info):
        # The file is probably read-only; make it writable and try again once.
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            func(target)
        except Exception:
            # A OneDrive / antivirus handle can outlive the first attempt.
            time.sleep(0.4)
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_on_error)
    else:                                   # Python 3.10 / 3.11
        shutil.rmtree(path, onerror=lambda f, t, e: _on_error(f, t, e))


def _clear_export_dir() -> None:
    """
    Empty the export folder but KEEP `.git` if it already exists.

    Two reasons:
      1. Windows: `.git/objects/**` are read-only, which is what raises
         "WinError 5: Access is denied" on deletion. `_rmtree_force` handles it.
      2. Keeping `.git` means your existing commit history and `origin` remote
         survive a rebuild, so an update is just:
             git add -A && git commit -m "..." && git push
         instead of re-initialising the repository every time.
    """
    if not EXPORT_DIR.exists():
        return
    for child in EXPORT_DIR.iterdir():
        if child.name == ".git":
            continue                      # preserve history + remote
        try:
            if child.is_dir():
                _rmtree_force(child)
            else:
                os.chmod(child, stat.S_IWRITE | stat.S_IREAD)
                child.unlink()
        except (PermissionError, OSError) as exc:
            raise SystemExit(
                f"[export] Could not remove {child}: {exc}\n"
                "         Close any editor, terminal or Explorer window inside "
                "dist\\git-export,\n         or pause OneDrive sync, then re-run."
            )


def build_export() -> Path:
    _clear_export_dir()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    for source in _iter_files(PROJECT_ROOT):
        relative = source.relative_to(PROJECT_ROOT)
        if str(relative).startswith("dist/"):
            continue
        target = EXPORT_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1

    for relative in FORCE_INCLUDE:
        source = PROJECT_ROOT / relative
        if source.is_file():
            target = EXPORT_DIR / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied += 1

    # A .gitignore in the export that does NOT exclude the model artefacts,
    # while still excluding secrets, databases and caches.
    (EXPORT_DIR / ".gitignore").write_text(
        "# Generated by scripts/export_for_git.py\n"
        ".env\n.env.*\n!.env.example\n"
        "__pycache__/\n*.py[cod]\n.pytest_cache/\n.venv/\nvenv/\n"
        "*.db\n*.db-wal\n*.db-shm\ndata/*.db*\n"
        ".streamlit/secrets.toml\n*.log\nlogs/*.log\n"
        "dist/\n.DS_Store\nThumbs.db\n",
        encoding="utf-8",
    )

    print(f"[export] {copied} file(s) -> {_display(EXPORT_DIR)}")
    for relative in FORCE_INCLUDE:
        marker = "included" if (EXPORT_DIR / relative).is_file() else "MISSING"
        print(f"[export]   {marker:9} {relative}")
    return EXPORT_DIR


def push(repo_url: str, message: str) -> int:
    if not (EXPORT_DIR / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=EXPORT_DIR, check=True)
        subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=EXPORT_DIR, check=True)
    subprocess.run(["git", "add", "-A"], cwd=EXPORT_DIR, check=True)
    committed = subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=EXPORT_DIR
    )
    if committed.returncode != 0:
        print("[push] nothing new to commit")
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=EXPORT_DIR, capture_output=True, text=True,
    ).stdout.strip() or "main"
    if branch == "HEAD":                      # fresh repo, no commits yet
        subprocess.run(["git", "branch", "-M", "main"], cwd=EXPORT_DIR, check=True)
        branch = "main"
    print(f"[push] git push -u origin {branch}")
    return subprocess.run(
        ["git", "push", "-u", "origin", branch, "--force"], cwd=EXPORT_DIR
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Git-ready copy of ScamShield AI")
    parser.add_argument("--check", action="store_true", help="run preflight checks only")
    parser.add_argument("--push", metavar="REPO_URL", help="commit and push the export folder")
    parser.add_argument("--message", default="Deploy ScamShield AI")
    args = parser.parse_args(argv)

    print("PREFLIGHT")
    checks = preflight()
    failed = 0
    for ok, label, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'}  {label:<38} {detail}")
        failed += 0 if ok else 1

    if failed:
        print(f"\n{failed} preflight check(s) failed - fix these before deploying.")
        return 1
    if args.check:
        print("\nAll preflight checks passed.")
        return 0

    print("\nEXPORT")
    build_export()

    if args.push:
        print("\nPUSH")
        return push(args.push, args.message)

    print(f"\nNext:\n  cd {_display(EXPORT_DIR)}")
    if (EXPORT_DIR / ".git").exists():
        # .git is preserved across rebuilds, so this is an update, not a fresh start.
        print("  (repository already initialised - remote and history kept)")
        print('  git add -A')
        print('  git commit -m "Update export"')
        print("  git push")
    else:
        print("  git init")
        print('  git commit -m "ScamShield AI - deployable snapshot"')
        print("  git branch -M main")
        print("  git remote add origin https://github.com/<you>/<repo>.git")
        print("  git push -u origin main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
