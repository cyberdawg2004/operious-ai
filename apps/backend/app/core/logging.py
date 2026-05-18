"""Structured logging setup.

Configures the root logger once at application startup. Local
environments get a human-readable formatter; staging/production emit
single-line JSON suitable for log aggregators (Datadog, Loki, CloudWatch,
etc.). All other modules just call `get_logger(__name__)`.

The handler also carries `RequestContextFilter`, which decorates every
record with the current request id — established by the request-context
middleware. Loggers do not need to know this; the filter sees every
record regardless of call site.
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.core.config import Settings, get_settings
from app.observability.authority_logging import AuthorityContextFilter
from app.observability.logging import RequestContextFilter

_configured: bool = False

#: Branch D — authority attribution. Every record carries the
#: ingress trust posture + the four identity axes alongside the
#: request id, so audit pipelines can correlate ``tenant_id`` /
#: ``principal_id`` provenance with log lines without joining
#: separate streams.
_JSON_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s %(request_id)s "
    "%(authority_source)s %(tenant_id)s %(principal_id)s "
    "%(organization_id)s %(environment_id)s %(message)s"
)
_TEXT_FORMAT = (
    "%(asctime)s | %(levelname)-8s | req=%(request_id)s "
    "| auth=%(authority_source)s tenant=%(tenant_id)s "
    "principal=%(principal_id)s | %(name)s | %(message)s"
)

_NOISY_LOGGERS = (
    "uvicorn.access",
    "httpx",
    "httpcore",
)


def configure_logging(settings: Settings | None = None) -> None:
    """Initialise root logging exactly once.

    Idempotent: safe to call multiple times (e.g. from `create_app` and
    lifespan handlers). Re-entry after the first call is a no-op.
    """

    global _configured
    if _configured:
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
    handler.addFilter(RequestContextFilter())
    handler.addFilter(AuthorityContextFilter())

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

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger.

    Prefer `get_logger(__name__)` so log records carry meaningful module
    paths in aggregation tools.
    """

    return logging.getLogger(name)


__all__ = ["configure_logging", "get_logger"]
