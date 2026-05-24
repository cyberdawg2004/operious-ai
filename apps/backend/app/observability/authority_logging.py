"""Authority attribution for structured logs (Branch D).

Decorates every :class:`logging.LogRecord` with the request-scoped
:class:`app.identity.AuthorityContext` axes plus the
``authority_source`` literal so audit pipelines, log aggregators,
and replay reconstruction can attribute every line of structured
output to:

* WHO was acting (``principal_id``)
* in WHICH tenant (``tenant_id``)
* under WHAT organizational scope (``organization_id``)
* against WHICH deployment (``environment_id``)
* via WHICH ingress trust posture (``authority_source``:
  ``verified`` / ``header`` / ``anonymous`` / ``-`` outside a
  request)

Constitutional positioning
──────────────────────────
* Read-only: the filter NEVER mutates the
  :class:`AuthorityContext` ContextVar — it only reads.
* Replay-safe: ContextVar reads are pure functions; running the
  filter twice produces identical records.
* Defense-in-depth: outside a request (background tasks, REPL,
  startup logs) every axis defaults to ``"-"`` so the log shape
  stays stable.

Capabilities are deliberately NOT logged inline (a single record
could carry hundreds of capability tokens). Audit consumers that
need capability provenance read it from the persisted
:class:`VerifiedIdentity` /
:class:`CapabilityGovernanceSubject` trail instead.
"""

from __future__ import annotations

import logging

from app.identity import (
    get_request_authority,
    get_request_authority_source,
)

_DEFAULT = "-"


class AuthorityContextFilter(logging.Filter):
    """Inject authority attribution into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        authority = get_request_authority()
        if authority is None:
            record.tenant_id = _record_value(record, "tenant_id")
            record.principal_id = _record_value(record, "principal_id")
            record.organization_id = _record_value(record, "organization_id")
            record.environment_id = _record_value(record, "environment_id")
        else:
            record.tenant_id = authority.tenant_id or _DEFAULT
            record.principal_id = authority.principal_id or _DEFAULT
            record.organization_id = (
                authority.organization_id or _DEFAULT
            )
            record.environment_id = authority.environment_id or _DEFAULT
        record.authority_source = (
            get_request_authority_source() or _DEFAULT
        )
        return True


def _record_value(record: logging.LogRecord, name: str) -> object:
    value = getattr(record, name, None)
    return value if value not in (None, "") else _DEFAULT


__all__ = ["AuthorityContextFilter"]
