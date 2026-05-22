"""Postgres cognition usage persistence."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.cognition.db.models import CognitionLLMUsageRow
from app.cognition.exceptions import CognitionPersistenceError
from app.cognition.identity import CognitionLLMUsageId
from app.cognition.models import CognitionLLMUsageRecord, CognitionLLMUsageStatus
from app.repositories.base import BaseRepository
from app.tenant.db.models import TenantRow


class PostgresCognitionUsagePersistence(BaseRepository):
    """Postgres-backed tenant usage ledger."""

    async def save_llm_usage(
        self,
        record: CognitionLLMUsageRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_tenant(record.tenant_id, expected_tenant_id)
        await self.session.merge(TenantRow(tenant_id=expected_tenant_id))
        try:
            async with self.session.begin_nested():
                existing = await self._usage_row(
                    record.usage_id,
                    expected_tenant_id=expected_tenant_id,
                )
                if existing is None:
                    self.session.add(_record_to_row(record))
                else:
                    _update_row(existing, record)
        except IntegrityError as exc:
            raise CognitionPersistenceError(
                f"LLM usage {record.usage_id!s} could not be persisted"
            ) from exc

    async def get_llm_usage(
        self,
        usage_id: CognitionLLMUsageId,
        *,
        expected_tenant_id: str,
    ) -> CognitionLLMUsageRecord | None:
        row = await self._usage_row(
            usage_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else _row_to_record(row)

    async def _usage_row(
        self,
        usage_id: CognitionLLMUsageId,
        *,
        expected_tenant_id: str,
    ) -> CognitionLLMUsageRow | None:
        stmt = select(CognitionLLMUsageRow).where(
            CognitionLLMUsageRow.usage_id == usage_id,
            CognitionLLMUsageRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _record_to_row(record: CognitionLLMUsageRecord) -> CognitionLLMUsageRow:
    return CognitionLLMUsageRow(
        usage_id=record.usage_id,
        tenant_id=record.tenant_id,
        execution_id=record.execution_id,
        dispatch_id=record.dispatch_id,
        session_id=record.session_id,
        provider=record.provider,
        model=record.model,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        total_tokens=record.total_tokens,
        estimated_cost_micro_usd=record.estimated_cost_micro_usd,
        status=record.status.value,
        created_at=record.created_at,
        metadata_json=dict(record.metadata),
    )


def _update_row(
    row: CognitionLLMUsageRow,
    record: CognitionLLMUsageRecord,
) -> None:
    row.execution_id = record.execution_id
    row.dispatch_id = record.dispatch_id
    row.session_id = record.session_id
    row.provider = record.provider
    row.model = record.model
    row.prompt_tokens = record.prompt_tokens
    row.completion_tokens = record.completion_tokens
    row.total_tokens = record.total_tokens
    row.estimated_cost_micro_usd = record.estimated_cost_micro_usd
    row.status = record.status.value
    row.created_at = record.created_at
    row.metadata_json = dict(record.metadata)


def _row_to_record(row: CognitionLLMUsageRow) -> CognitionLLMUsageRecord:
    return CognitionLLMUsageRecord(
        usage_id=CognitionLLMUsageId(row.usage_id),
        tenant_id=row.tenant_id,
        execution_id=row.execution_id,
        dispatch_id=row.dispatch_id,
        session_id=row.session_id,
        provider=row.provider,
        model=row.model,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        estimated_cost_micro_usd=row.estimated_cost_micro_usd,
        status=CognitionLLMUsageStatus(row.status),
        created_at=row.created_at,
        metadata=_as_dict(row.metadata_json),
    )


def _enforce_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise CognitionPersistenceError(
            "record tenant_id does not match expected_tenant_id"
        )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        data = cast(dict[object, Any], value)
        return {str(k): v for k, v in data.items()}
    return {}


__all__ = ["PostgresCognitionUsagePersistence"]
