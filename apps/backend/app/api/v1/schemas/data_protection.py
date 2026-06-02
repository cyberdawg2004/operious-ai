"""Transport contracts for data-protection operational admin APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.data_protection.crypto import (
    DataProtectionErasureRequestRecord,
    DataProtectionLegalHoldRecord,
)

LegalHoldScopeValue = Literal["tenant", "subject", "session"]
ErasureStatusValue = Literal["proposed", "approved", "rejected", "executed"]


class ErasureRequestCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2_000)


class ErasureRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: uuid.UUID
    tenant_id: str
    subject_id: str
    reason: str
    status: ErasureStatusValue
    proposed_by: str
    proposed_at: datetime
    approved_by: str | None
    approved_at: datetime | None
    executed_at: datetime | None
    blocked_reason: str | None

    @classmethod
    def from_record(
        cls,
        record: DataProtectionErasureRequestRecord,
    ) -> "ErasureRequestResponse":
        return cls(
            request_id=record.request_id,
            tenant_id=record.tenant_id,
            subject_id=record.subject_id,
            reason=record.reason,
            status=record.status.value,
            proposed_by=record.proposed_by,
            proposed_at=record.proposed_at,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            executed_at=record.executed_at,
            blocked_reason=record.blocked_reason,
        )


class LegalHoldCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: LegalHoldScopeValue
    scope_id: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=1, max_length=2_000)


class LegalHoldResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    hold_id: uuid.UUID
    tenant_id: str
    scope: LegalHoldScopeValue
    scope_id: str
    reason: str
    created_by: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: DataProtectionLegalHoldRecord) -> "LegalHoldResponse":
        return cls(
            hold_id=record.hold_id,
            tenant_id=record.tenant_id,
            scope=cast(LegalHoldScopeValue, record.scope),
            scope_id=record.scope_id,
            reason=record.reason,
            created_by=record.created_by,
            created_at=record.created_at,
        )


class LegalHoldListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[LegalHoldResponse]


class RetentionPolicyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    retention_days: int


class RetentionPolicyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    retention_days: int


__all__ = [
    "ErasureRequestCreateRequest",
    "ErasureRequestResponse",
    "LegalHoldCreateRequest",
    "LegalHoldListResponse",
    "LegalHoldResponse",
    "RetentionPolicyRequest",
    "RetentionPolicyResponse",
]
