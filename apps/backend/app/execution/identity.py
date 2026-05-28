"""Execution identity primitives.

``dispatch_id`` is not ``execution_id``. Dispatch identifies a
coordination decision; execution identifies the durable right for a
worker to perform exactly one unit of work derived from that decision.
"""

from __future__ import annotations

import itertools
import secrets
import uuid
from typing import NewType

from app.identity import project_optional_str


ExecutionId = NewType("ExecutionId", uuid.UUID)
ExecutionAttemptId = NewType("ExecutionAttemptId", uuid.UUID)
ExecutionOutboxId = NewType("ExecutionOutboxId", uuid.UUID)
ExecutionOutboxClaimId = NewType("ExecutionOutboxClaimId", uuid.UUID)


_EXECUTION_NAMESPACE: uuid.UUID = uuid.UUID(
    "e0ec7001-0001-4001-8001-000000000001"
)
_OUTBOX_NAMESPACE: uuid.UUID = uuid.UUID(
    "e0ec7001-0002-4002-8002-000000000002"
)
_ATTEMPT_NAMESPACE: uuid.UUID = uuid.UUID(
    "e0ec7001-0003-4003-8003-000000000003"
)
_OUTBOX_CLAIM_NAMESPACE: uuid.UUID = uuid.UUID(
    "e0ec7001-0004-4004-8004-000000000004"
)
_RUNTIME_BOOT_ID = secrets.token_urlsafe(32)
_RUNTIME_COUNTER = itertools.count()


def generate_execution_id() -> ExecutionId:
    return ExecutionId(
        uuid.uuid5(
            _EXECUTION_NAMESPACE,
            f"runtime|execution|{_RUNTIME_BOOT_ID}|{next(_RUNTIME_COUNTER)}",
        )
    )


def derive_execution_id(
    *,
    kind: str,
    dispatch_id: str,
    session_id: str,
    tenant_id: str | None,
) -> ExecutionId:
    """Derive the replay-stable identity of an execution intent."""

    if not kind:
        raise ValueError("derive_execution_id requires a non-empty kind")
    if not dispatch_id:
        raise ValueError(
            "derive_execution_id requires a non-empty dispatch_id"
        )
    if not session_id:
        raise ValueError(
            "derive_execution_id requires a non-empty session_id"
        )
    seed = (
        f"{kind}|"
        f"{project_optional_str(tenant_id)}|"
        f"{dispatch_id}|"
        f"{session_id}"
    )
    return ExecutionId(uuid.uuid5(_EXECUTION_NAMESPACE, seed))


def derive_outbox_id(*, execution_id: uuid.UUID) -> ExecutionOutboxId:
    return ExecutionOutboxId(
        uuid.uuid5(_OUTBOX_NAMESPACE, str(execution_id))
    )


def derive_outbox_claim_id(
    *,
    outbox_id: uuid.UUID | str,
    publisher_id: str,
    publish_attempt_count: int,
) -> ExecutionOutboxClaimId:
    if not publisher_id:
        raise ValueError("publisher_id is required")
    if publish_attempt_count < 1:
        raise ValueError("publish_attempt_count must be >= 1")
    return ExecutionOutboxClaimId(
        uuid.uuid5(
            _OUTBOX_CLAIM_NAMESPACE,
            f"{outbox_id}|{publisher_id}|{publish_attempt_count}",
        )
    )


def derive_attempt_id(
    *, execution_id: uuid.UUID, attempt_number: int
) -> ExecutionAttemptId:
    if attempt_number < 1:
        raise ValueError("attempt_number must be >= 1")
    seed = f"{execution_id}|{attempt_number}"
    return ExecutionAttemptId(uuid.uuid5(_ATTEMPT_NAMESPACE, seed))


def as_attempt_id(value: uuid.UUID | str) -> ExecutionAttemptId:
    return ExecutionAttemptId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_execution_id(value: uuid.UUID | str) -> ExecutionId:
    return ExecutionId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_outbox_id(value: uuid.UUID | str) -> ExecutionOutboxId:
    return ExecutionOutboxId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_outbox_claim_id(value: uuid.UUID | str) -> ExecutionOutboxClaimId:
    return ExecutionOutboxClaimId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


__all__ = [
    "ExecutionAttemptId",
    "ExecutionId",
    "ExecutionOutboxClaimId",
    "ExecutionOutboxId",
    "as_attempt_id",
    "as_execution_id",
    "as_outbox_claim_id",
    "as_outbox_id",
    "derive_attempt_id",
    "derive_execution_id",
    "derive_outbox_claim_id",
    "derive_outbox_id",
    "generate_execution_id",
]
