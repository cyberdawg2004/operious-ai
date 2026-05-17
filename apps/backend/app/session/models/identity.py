"""`SessionIdentity` — composite continuity identity.

Pairs the deterministic `SessionId` with the principal/tenant
coordinates that scope it. The `external_handle` is an opaque
string that lets callers de-duplicate sessions across replays
(e.g. a Zendesk ticket id, a WhatsApp wa_id, a synthetic
"order-12345" handle).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.session.enums import SessionScope
from app.session.identity import SessionId


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Composite, immutable continuity identity.

    Attributes:
        session_id:       Stable identifier (UUID5-derivable).
        scope:            Authority/scoping classification.
        tenant_id:        Tenant this session belongs to.
                           ``None`` for substrate-internal sessions.
        principal_id:     Principal (user/agent) anchoring the
                           session. ``None`` when the scope does
                           not require a principal.
        external_handle:  Opaque external identifier the caller
                           supplied to anchor the session. The
                           substrate treats this as substrate-
                           agnostic; it is preserved verbatim.
    """

    session_id: SessionId
    scope: SessionScope
    external_handle: str
    tenant_id: str | None = None
    principal_id: str | None = None

    def __post_init__(self) -> None:
        if not self.external_handle:
            raise ValueError(
                "SessionIdentity.external_handle must be a "
                "non-empty string"
            )


__all__ = ["SessionIdentity"]
