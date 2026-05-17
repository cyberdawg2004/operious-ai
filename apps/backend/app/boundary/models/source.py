"""`BoundarySource` — typed declaration of an external system endpoint.

The source pairs a canonical `BoundarySourceType` with a free-form
``source_id`` that uniquely identifies the external endpoint
within that type (e.g. a Zendesk subdomain, a WhatsApp business
phone number, a Twilio account SID).

The substrate trusts the declared `source_id` — it does not
re-validate it. Adapters are responsible for asserting the source
matches their authentication context BEFORE constructing the
`BoundarySource`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.boundary.enums import BoundarySourceType


@dataclass(frozen=True, slots=True)
class BoundarySource:
    """Typed declaration of an external system endpoint.

    Attributes:
        source_type: Canonical classification.
        source_id:   Endpoint identifier within `source_type`.
        tenant_id:   Tenant that owns the endpoint. ``None`` for
                      single-tenant deployments.
        display_name: Human-readable label (audit-only).
        metadata:    Free-form, propagated through persistence.
    """

    source_type: BoundarySourceType
    source_id: str
    tenant_id: str | None = None
    display_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError(
                "BoundarySource.source_id must be a non-empty string"
            )


__all__ = ["BoundarySource"]
