"""Logging enrichment.

A single `logging.Filter` that decorates every log record with the
current request id (or `"-"` when emitted outside a request). It works
uniformly for the text formatter (`%(request_id)s` in the format
string) and the JSON formatter (records become top-level `request_id`
fields).

Filters live in `observability` (not `core/logging`) because they are
the seam where the platform's runtime context meets the logging stack;
keeping them here means new context fields (trace_id, actor_id, agent
run_id) get added in one place and inherited by every handler.
"""

from __future__ import annotations

import logging

from app.observability.context import get_request_id

_DEFAULT_REQUEST_ID = "-"


class RequestContextFilter(logging.Filter):
    """Attach request-scoped context to every log record.

    `ContextVar` lookup is O(1) and copy-on-write across tasks, so this
    is safe to install on every handler in every environment.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or _DEFAULT_REQUEST_ID
        return True


__all__ = ["RequestContextFilter"]
