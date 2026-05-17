"""Canonical session metadata vocabulary.

Provides the namespaced metadata-key catalogue. The catalogue is
pinned in `tests/test_session_invariants.py`.

Metadata-key namespacing rule: every key the substrate emits is
prefixed ``session.*``. This guarantees no collision with caller-
supplied free-form metadata or with sibling-substrate namespaces
(``coordination.*``, ``coordination.policy.*``,
``coordination.topology.*``, ``arbitration.*``, ``boundary.*``).
"""

from __future__ import annotations

from enum import StrEnum


class SessionMetadataKey(StrEnum):
    """Canonical metadata keys the substrate writes onto envelopes/traces."""

    SESSION_ID = "session.session_id"
    EVENT_ID = "session.event_id"
    LINEAGE_ID = "session.lineage_id"
    CORRELATION_ID = "session.correlation_id"
    RECONSTRUCTION_ID = "session.reconstruction_id"
    TRACE_ID = "session.trace_id"
    SCOPE = "session.scope"
    TENANT_ID = "session.tenant_id"
    PRINCIPAL_ID = "session.principal_id"
    EXTERNAL_HANDLE = "session.external_handle"
    LIFECYCLE_PHASE = "session.lifecycle_phase"
    LIFECYCLE_REASON = "session.lifecycle_reason"
    EVENT_KIND = "session.event_kind"
    EVENT_SEQUENCE = "session.event_sequence"
    CONTINUITY_MODE = "session.continuity_mode"
    RECONSTRUCTION_STATUS = "session.reconstruction_status"
    OPENED_AT = "session.opened_at"
    OCCURRED_AT = "session.occurred_at"
    RECORDED_AT = "session.recorded_at"
    CORRELATION_KIND = "session.correlation_kind"
    EXTERNAL_ARTIFACT_ID = "session.external_artifact_id"


__all__ = ["SessionMetadataKey"]
