"""Boundary persistence — storage-agnostic contracts."""

from app.boundary.persistence.memory import (
    InMemoryBoundaryPersistence,
)
from app.boundary.persistence.models import (
    BoundaryEgressQuery,
    BoundaryIngressQuery,
    BoundaryRecordPage,
)
from app.boundary.persistence.postgres import (
    PostgresBoundaryPersistence,
)
from app.boundary.persistence.records import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
    WebhookNonceRecord,
)
from app.boundary.persistence.repository import (
    BoundaryPersistenceProtocol,
)
from app.boundary.persistence.serializers import (
    egress_envelope_to_record,
    egress_result_to_record,
    ingress_envelope_to_record,
    ingress_record_to_result,
    ingress_result_to_record,
)

__all__ = [
    "BoundaryEgressQuery",
    "BoundaryEgressRecord",
    "BoundaryIngressQuery",
    "BoundaryIngressRecord",
    "BoundaryPersistenceProtocol",
    "BoundaryRecordPage",
    "InMemoryBoundaryPersistence",
    "PostgresBoundaryPersistence",
    "WebhookNonceRecord",
    "egress_envelope_to_record",
    "egress_result_to_record",
    "ingress_envelope_to_record",
    "ingress_record_to_result",
    "ingress_result_to_record",
]
