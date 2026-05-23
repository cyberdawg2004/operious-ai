"""Postgres cognition usage persistence."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.cognition.db.models import CognitionAuditRecordRow, CognitionLLMUsageRow
from app.cognition.exceptions import CognitionPersistenceError
from app.cognition.identity import CognitionAuditId, CognitionLLMUsageId
from app.cognition.models import (
    CognitionAuditRecord,
    CognitionLLMUsageRecord,
    CognitionLLMUsageStatus,
)
from app.repositories.base import BaseRepository
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.db.models import TenantRow


class PostgresCognitionUsagePersistence(BaseRepository):
    """Postgres-backed tenant usage ledger."""

    __slots__ = ("_audit_encryptor",)

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit_encryptor: TenantCredentialEncryptor | None = None,
    ) -> None:
        super().__init__(session)
        self._audit_encryptor = audit_encryptor

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

    async def save_cognition_audit(
        self,
        record: CognitionAuditRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_tenant(record.tenant_id, expected_tenant_id)
        encryptor = self._require_audit_encryptor()
        await self.session.merge(TenantRow(tenant_id=expected_tenant_id))
        try:
            async with self.session.begin_nested():
                existing = await self._audit_row(
                    record.audit_id,
                    expected_tenant_id=expected_tenant_id,
                )
                if existing is None:
                    self.session.add(_audit_record_to_row(record, encryptor))
                else:
                    _update_audit_row(existing, record, encryptor)
        except IntegrityError as exc:
            raise CognitionPersistenceError(
                f"cognition audit {record.audit_id!s} could not be persisted"
            ) from exc

    async def get_cognition_audit(
        self,
        audit_id: CognitionAuditId,
        *,
        expected_tenant_id: str,
    ) -> CognitionAuditRecord | None:
        row = await self._audit_row(
            audit_id,
            expected_tenant_id=expected_tenant_id,
        )
        if row is None:
            return None
        return _audit_row_to_record(row, self._require_audit_encryptor())

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

    async def _audit_row(
        self,
        audit_id: CognitionAuditId,
        *,
        expected_tenant_id: str,
    ) -> CognitionAuditRecordRow | None:
        stmt = select(CognitionAuditRecordRow).where(
            CognitionAuditRecordRow.audit_id == audit_id,
            CognitionAuditRecordRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _require_audit_encryptor(self) -> TenantCredentialEncryptor:
        if self._audit_encryptor is None:
            raise CognitionPersistenceError(
                "cognition audit encryption is not configured"
            )
        return self._audit_encryptor


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


def _audit_record_to_row(
    record: CognitionAuditRecord,
    encryptor: TenantCredentialEncryptor,
) -> CognitionAuditRecordRow:
    return CognitionAuditRecordRow(
        audit_id=record.audit_id,
        tenant_id=record.tenant_id,
        execution_id=record.execution_id,
        usage_id=record.usage_id,
        prompt_full=_encrypt_text(
            encryptor,
            tenant_id=record.tenant_id,
            key="prompt_full",
            value=record.prompt_full,
        ),
        completion_full=_encrypt_text(
            encryptor,
            tenant_id=record.tenant_id,
            key="completion_full",
            value=record.completion_full,
        ),
        prompt_sha256=record.prompt_sha256,
        completion_sha256=record.completion_sha256,
        model_name=record.model_name,
        token_usage=dict(record.token_usage),
        captured_at=record.captured_at,
    )


def _update_audit_row(
    row: CognitionAuditRecordRow,
    record: CognitionAuditRecord,
    encryptor: TenantCredentialEncryptor,
) -> None:
    row.execution_id = record.execution_id
    row.usage_id = record.usage_id
    row.prompt_full = _encrypt_text(
        encryptor,
        tenant_id=record.tenant_id,
        key="prompt_full",
        value=record.prompt_full,
    )
    row.completion_full = _encrypt_text(
        encryptor,
        tenant_id=record.tenant_id,
        key="completion_full",
        value=record.completion_full,
    )
    row.prompt_sha256 = record.prompt_sha256
    row.completion_sha256 = record.completion_sha256
    row.model_name = record.model_name
    row.token_usage = dict(record.token_usage)
    row.captured_at = record.captured_at


def _audit_row_to_record(
    row: CognitionAuditRecordRow,
    encryptor: TenantCredentialEncryptor,
) -> CognitionAuditRecord:
    return CognitionAuditRecord(
        audit_id=CognitionAuditId(row.audit_id),
        tenant_id=row.tenant_id,
        execution_id=row.execution_id,
        usage_id=(
            CognitionLLMUsageId(row.usage_id)
            if row.usage_id is not None
            else None
        ),
        prompt_full=_decrypt_text(
            encryptor,
            tenant_id=row.tenant_id,
            key="prompt_full",
            encrypted=row.prompt_full,
        ),
        completion_full=_decrypt_text(
            encryptor,
            tenant_id=row.tenant_id,
            key="completion_full",
            encrypted=row.completion_full,
        ),
        prompt_sha256=row.prompt_sha256,
        completion_sha256=row.completion_sha256,
        model_name=row.model_name,
        token_usage=_as_dict(row.token_usage),
        captured_at=row.captured_at,
    )


def _encrypt_text(
    encryptor: TenantCredentialEncryptor,
    *,
    tenant_id: str,
    key: str,
    value: str,
) -> bytes:
    return encryptor.encrypt(
        tenant_id=tenant_id,
        credentials={key: value},
    )


def _decrypt_text(
    encryptor: TenantCredentialEncryptor,
    *,
    tenant_id: str,
    key: str,
    encrypted: bytes,
) -> str:
    decoded = encryptor.decrypt(
        tenant_id=tenant_id,
        encrypted_credentials=encrypted,
    )
    value = decoded.get(key)
    if not isinstance(value, str):
        raise CognitionPersistenceError(
            f"cognition audit encrypted field {key!r} is invalid"
        )
    return value


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
