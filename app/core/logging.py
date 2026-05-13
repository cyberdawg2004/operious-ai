"""Structured logging setup.

Configures the root logger once at application startup. Local
environments get a human-readable formatter; staging/production emit
single-line JSON suitable for log aggregators (Datadog, Loki, CloudWatch,
etc.). All other modules just call `get_logger(__name__)`.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from pythonjsonlogger.json import JsonFormatter

from app.core.config import Settings, get_settings

_CONFIGURED: bool = False

_JSON_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_TEXT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_NOISY_LOGGERS = (
    "uvicorn.access",
    "httpx",
    "httpcore",
)


def configure_logging(settings: Optional[Settings] = None) -> None:
    """Initialise root logging exactly once.

    Idempotent: safe to call multiple times (e.g. from `create_app` and
    lifespan handlers). Re-entry after the first call is a no-op.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = settings or get_settings()
    level = (settings.LOG_LEVEL or "INFO").upper()

    handler = logging.StreamHandler(sys.stdout)

    if settings.use_json_logs:
        formatter: logging.Formatter = JsonFormatter(
            _JSON_FORMAT,
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    else:
        formatter = logging.Formatter(_TEXT_FORMAT)

    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root.info(
        "logging_initialised",
        extra={
            "environment": settings.ENVIRONMENT,
            "level": level,
            "format": "json" if settings.use_json_logs else "text",
        },
    )

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger.

    Prefer `get_logger(__name__)` so log records carry meaningful module
    paths in aggregation tools.
    """

    return logging.getLogger(name)
