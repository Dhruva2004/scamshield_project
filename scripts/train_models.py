"""
ScamShield AI - scripts/train_models.py
=======================================
Convenience entry point so you can run training without remembering module paths.

    python scripts/train_models.py

It simply delegates to ml/training/train.py, adding the project root to
sys.path so the `ml.` and `backend.` packages import cleanly.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.training.train import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
