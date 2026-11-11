"""
ScamShield AI - ml/data/download_dataset.py
===========================================
Downloads and prepares the UCI SMS Spam Collection dataset.

Dataset facts (verified, not assumed)
-------------------------------------
    Source : UCI Machine Learning Repository, dataset id 228
    URL    : https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip
    Format : a single tab-separated file `SMSSpamCollection` (no header)
    Rows   : 5,572 (4,827 ham / 747 spam)
    Columns: label ('ham' | 'spam'), text

Why download instead of committing the data?
-------------------------------------------
Data files bloat a git repository and often carry unclear licensing. A short,
reproducible download script is the professional pattern: anyone who clones the
project can rebuild the exact same dataset.

Usage
-----
    python -m ml.data.download_dataset            # download + prepare
    python -m ml.data.download_dataset --force    # re-download

If you are offline, download the ZIP manually and place it at
ml/data/raw/sms_spam_collection.zip, then re-run this script.
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pandas as pd

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "ml" / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "ml" / "data" / "processed"

ZIP_PATH = RAW_DIR / "sms_spam_collection.zip"
TXT_PATH = RAW_DIR / "SMSSpamCollection"
CSV_PATH = PROCESSED_DIR / "sms_spam.csv"

DATASET_URL = "https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip"

# Fallback mirror (used only if the primary URL fails).
MIRROR_URLS = [
    "https://archive.ics.uci.edu/ml/machine-learning-databases/00228/smsspamcollection.zip",
]


def download(force: bool = False) -> Path:
    """
    Download the dataset ZIP to ml/data/raw/.

    Returns the path to the ZIP. Re-uses an existing download unless `force`.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if ZIP_PATH.exists() and not force:
        print(f"[download] Using existing archive: {ZIP_PATH}")
        return ZIP_PATH

    if force and ZIP_PATH.exists():
        ZIP_PATH.unlink()

    for url in [DATASET_URL, *MIRROR_URLS]:
        print(f"[download] GET {url}")
        try:
            with urlopen(url, timeout=60) as response:
                payload = response.read()
            if len(payload) < 50_000:
                print(f"[download] Suspiciously small response ({len(payload)} bytes), skipping")
                continue
            ZIP_PATH.write_bytes(payload)
            print(f"[download] Saved {len(payload):,} bytes -> {ZIP_PATH}")
            return ZIP_PATH
        except (URLError, TimeoutError, OSError) as exc:
            print(f"[download] Failed ({exc}); trying next mirror")

    raise SystemExit(
        "Could not download the dataset.\n"
        f"Place 'sms_spam_collection.zip' manually in {RAW_DIR} and re-run:\n"
        "    python -m ml.data.download_dataset"
    )


def extract(zip_path: Path) -> Path:
    """
    Extract `SMSSpamCollection` from the archive.

    The archive contains the data file and a readme; we only need the former.
    """
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        candidates = [n for n in names if n.lower().endswith("smsspamcollection")]
        if not candidates:
            raise SystemExit(f"No SMSSpamCollection file inside {zip_path}. Found: {names}")
        member = candidates[0]
        with archive.open(member) as source:
            TXT_PATH.write_bytes(source.read())
    print(f"[extract] {member} -> {TXT_PATH}")
    return TXT_PATH


def prepare_csv(txt_path: Path) -> pd.DataFrame:
    """
    Convert the raw tab-separated file into a clean CSV.

    Cleaning steps (all justified):
      1. Read with an explicit separator and no header.
      2. Normalise label casing.
      3. Drop exact duplicate messages -> the SMS Spam Collection contains
         ~400 duplicates; leaving them in leaks test data into the training set
         and inflates accuracy artificially.
      4. Drop empty messages.
      5. Encode the label: ham=0, spam=1 (single source of truth for the whole
         pipeline).
    """
    frame = pd.read_csv(
        txt_path,
        sep="\t",
        header=None,
        names=["label", "text"],
        quoting=3,          # csv.QUOTE_NONE - messages contain quotes
        encoding="utf-8",
        on_bad_lines="skip",
    )

    frame["label"] = frame["label"].str.strip().str.lower()
    frame = frame[frame["label"].isin({"ham", "spam"})].copy()
    frame["text"] = frame["text"].astype(str).str.strip()

    rows_before = len(frame)
    before_dupes = len(frame)
    frame = frame.drop_duplicates(subset=["text"], keep="first")
    duplicates_removed = before_dupes - len(frame)

    frame = frame[frame["text"].str.len() > 0].copy()
    frame["label_encoded"] = (frame["label"] == "spam").astype(int)
    frame = frame.reset_index(drop=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CSV_PATH, index=False, encoding="utf-8")

    print("\n[prepare] Dataset summary")
    print(f"  raw rows              : {rows_before:,}")
    print(f"  duplicates removed    : {duplicates_removed:,}")
    print(f"  final rows            : {len(frame):,}")
    print(f"  ham / spam            : {(frame.label == 'ham').sum():,} / "
          f"{(frame.label == 'spam').sum():,}")
    print(f"  spam share            : {frame.label_encoded.mean():.2%}")
    print(f"  saved to              : {CSV_PATH}")
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the UCI SMS Spam Collection")
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    args = parser.parse_args(argv)

    zip_path = download(force=args.force)
    txt_path = extract(zip_path)
    prepare_csv(txt_path)
    print("\n[ok] Dataset ready. Next: python scripts/train_models.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
