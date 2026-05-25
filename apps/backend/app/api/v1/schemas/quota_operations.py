"""Transport contracts for operator quota operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.runtime.quota_runtime import QuotaStatus
from app.services.quota_operations_service import (
    ProviderQuotaRecord,
    ProviderQuotaRecordPage,
)

QuotaCircuitStateValue = Literal["force_open", "force_close"]


class QuotaCircuitOverrideRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    circuit_state: QuotaCircuitStateValue | None = None
    reason: str = Field(min_length=1, max_length=2_000)


class QuotaStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    provider: str
    model: str
    requests_per_minute_count: int
    requests_per_minute_limit: int
    requests_per_hour_count: int
    requests_per_hour_limit: int
    tokens_per_minute_count: int | None
    tokens_per_minute_limit: int
    operator_circuit_state: QuotaCircuitStateValue | None
    redis_available: bool

    @classmethod
    def from_status(cls, status: QuotaStatus) -> "QuotaStatusResponse":
        return cls(
            tenant_id=status.tenant_id,
            provider=status.provider,
            model=status.model,
            requests_per_minute_count=status.requests_per_minute_count,
            requests_per_minute_limit=status.requests_per_minute_limit,
            requests_per_hour_count=status.requests_per_hour_count,
            requests_per_hour_limit=status.requests_per_hour_limit,
            tokens_per_minute_count=status.tokens_per_minute_count,
            tokens_per_minute_limit=status.tokens_per_minute_limit,
            operator_circuit_state=status.operator_circuit_state,
            redis_available=status.redis_available,
        )


class ProviderQuotaRecordResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    provider: str
    model: str
    quota_type: str
    window_start: datetime
    window_count: int
    quota_limit: int
    is_exhausted: bool
    operator_circuit_state: QuotaCircuitStateValue | None
    operator_set_by: str | None
    operator_set_at: datetime | None
    operator_reason: str | None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: ProviderQuotaRecord,
    ) -> "ProviderQuotaRecordResponse":
        return cls(
            id=record.id,
            tenant_id=record.tenant_id,
            provider=record.provider,
            model=record.model,
            quota_type=record.quota_type,
            window_start=record.window_start,
            window_count=record.window_count,
            quota_limit=record.quota_limit,
            is_exhausted=record.is_exhausted,
            operator_circuit_state=record.operator_circuit_state,
            operator_set_by=record.operator_set_by,
            operator_set_at=record.operator_set_at,
            operator_reason=record.operator_reason,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=dict(record.metadata),
        )


class ProviderQuotaRecordPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ProviderQuotaRecordResponse]
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: ProviderQuotaRecordPage,
    ) -> "ProviderQuotaRecordPageResponse":
        return cls(
            items=[
                ProviderQuotaRecordResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


__all__ = [
    "ProviderQuotaRecordPageResponse",
    "ProviderQuotaRecordResponse",
    "QuotaCircuitOverrideRequest",
    "QuotaStatusResponse",
]
