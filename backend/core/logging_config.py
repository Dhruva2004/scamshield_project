"""
ScamShield AI - backend/core/logging_config.py
==============================================
Central logging setup.

Why: `print()` is fine for a script, but a real service needs
  * log levels (DEBUG / INFO / WARNING / ERROR),
  * timestamps,
  * the module name that produced each line,
  * one consistent format across FastAPI, the ML layer and the services.

Call `configure_logging()` exactly once, at process start (in main.py).
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """
    Configure the root logger for the whole application.

    Parameters
    ----------
    level : str
        One of DEBUG, INFO, WARNING, ERROR, CRITICAL (case-insensitive).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    numeric_level = getattr(logging, str(level).upper(), logging.INFO)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(numeric_level)
    # Remove pre-existing handlers (uvicorn adds its own) to avoid duplicates.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)

    # Third-party loggers we do not want to spam the console.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Tiny convenience wrapper so modules can do get_logger(__name__)."""
    return logging.getLogger(name)
