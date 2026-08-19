"""Immutable, synthetic-only contract for the Northstar recording fixture."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


TENANT_ID = "northstar-clueso-demo"
SESSION_ID = uuid.UUID("2e5a8e82-9184-520d-a027-6190977e6f4b")
SEEDED_SESSION_SEQUENCE_HEAD = 2
_NAMESPACE = uuid.UUID("4fd2a04c-66c5-5e97-8f7e-30f77757c73a")
_ACTION_APPROVAL_NAMESPACE = uuid.UUID("aa6e7001-0007-4007-8007-000000000007")
_STARTED_AT = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)


def stable_id(name: str) -> uuid.UUID:
    """Return a stable fixture identifier; never derive from customer input."""
    return uuid.uuid5(_NAMESPACE, name)


@dataclass(frozen=True, slots=True)
class NorthstarDemoManifest:
    tenant_id: str = TENANT_ID
    session_id: uuid.UUID = SESSION_ID
    customer_name: str = "Maya Chen"
    customer_email: str = "maya.chen@example.com"
    opened_at: datetime = _STARTED_AT

    @property
    def customer_message_at(self) -> datetime:
        return self.opened_at + timedelta(minutes=1)

    @property
    def governance_at(self) -> datetime:
        return self.opened_at + timedelta(minutes=2)

    @property
    def proposal_at(self) -> datetime:
        return self.opened_at + timedelta(minutes=3)

    @property
    def inspection_at(self) -> datetime:
        return self.opened_at + timedelta(minutes=4)

    @property
    def governance_decision_id(self) -> uuid.UUID:
        return stable_id("governance-decision")

    @property
    def proposal_id(self) -> uuid.UUID:
        return stable_id("resolution-proposal")

    @property
    def approval_id(self) -> uuid.UUID:
        # Mirrors the immutable repository identifier contract; its input is
        # fixed by this manifest, never by an operator argument.
        return uuid.uuid5(
            _ACTION_APPROVAL_NAMESPACE,
            f"{self.tenant_id}|{self.approval_idempotency_key}",
        )

    @property
    def approval_idempotency_key(self) -> uuid.UUID:
        return stable_id("replacement-order-idempotency")

    @property
    def inspection_id(self) -> uuid.UUID:
        return stable_id("supervisor-inspection")

    @property
    def execution_id(self) -> uuid.UUID:
        return stable_id("synthetic-execution")

    @property
    def qa_score_id(self) -> uuid.UUID:
        return stable_id("qa-score")


MANIFEST = NorthstarDemoManifest()
