"""Canonical boundary metadata vocabulary.

Provides the namespaced metadata-key catalogue + canonical
key-classification helpers. The catalogue is pinned in
`tests/test_boundary_invariants.py`.

Metadata-key namespacing rule: every key the substrate emits is
prefixed ``boundary.*``. This guarantees no collision with caller-
supplied free-form metadata or with sibling-substrate namespaces
(``coordination.*``, ``coordination.policy.*``,
``coordination.topology.*``, ``arbitration.*``, …).
"""

from __future__ import annotations

from enum import StrEnum


class BoundaryMetadataKey(StrEnum):
    """Canonical metadata keys the substrate writes onto envelopes / traces."""

    EVENT_ID = "boundary.event_id"
    INGRESS_ID = "boundary.ingress_id"
    EGRESS_ID = "boundary.egress_id"
    DIRECTION = "boundary.direction"
    SOURCE_TYPE = "boundary.source_type"
    SOURCE_ID = "boundary.source_id"
    EXTERNAL_MESSAGE_ID = "boundary.external_message_id"
    EXTERNAL_CONVERSATION_ID = "boundary.external_conversation_id"
    MESSAGE_TYPE = "boundary.message_type"
    NORMALIZATION_STATUS = "boundary.normalization_status"
    REPLAY_DISPOSITION = "boundary.replay_disposition"
    REPLAY_KEY = "boundary.replay_key"
    ORIGINAL_EVENT_ID = "boundary.original_event_id"
    ADAPTER_NAME = "boundary.adapter_name"
    TENANT_ID = "boundary.tenant_id"
    CORRELATION_ID = "boundary.correlation_id"
    REQUEST_ID = "boundary.request_id"
    RECEIVED_AT = "boundary.received_at"
    EXTERNAL_EMITTED_AT = "boundary.external_emitted_at"


__all__ = ["BoundaryMetadataKey"]
