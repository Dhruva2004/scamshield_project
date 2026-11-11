"""
ScamShield AI - scripts/seed_demo_data.py
=========================================
Populate the database with demo scans so the dashboard looks alive during a
presentation.

    python scripts/seed_demo_data.py            # add demo scans
    python scripts/seed_demo_data.py --clear    # remove ALL history first

Why this is honest
------------------
These rows are produced by running the REAL pipeline over the curated sample
messages - the same code path a user hits. Nothing is fabricated: the risk
scores, rule findings and probabilities are computed at seed time.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.samples import SAMPLES
from backend.database.connection import init_db
from backend.database.repositories import scan_repository
from backend.schemas.common import Language
from backend.schemas.scan import ScanRequest
from backend.services.scan_service import get_scan_service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed demo scan history")
    parser.add_argument("--clear", action="store_true", help="clear existing history first")
    parser.add_argument(
        "--no-explanation",
        action="store_true",
        help="skip the explanation layer (faster seeding)",
    )
    args = parser.parse_args(argv)

    init_db()
    if args.clear:
        removed = scan_repository.clear_all()
        print(f"[seed] cleared {removed} existing scan(s)")

    service = get_scan_service()
    created = 0
    for sample in SAMPLES:
        # Use the sample's own language hint where the text is Hinglish, so the
        # seeded explanation matches what a real user would receive.
        language = Language.HINGLISH if sample["id"] == "hinglish" else Language.ENGLISH
        response = service.scan(
            ScanRequest(
                text=sample["text"],
                language=language,
                include_explanation=not args.no_explanation,
            )
        )
        created += 1
        print(
            f"[seed] {sample['id']:22} -> {response.risk.level.value:9} "
            f"score={response.risk.score:3} ({response.processing_ms} ms)"
        )

    print(f"\n[seed] inserted {created} scan(s). Open the dashboard to see them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
