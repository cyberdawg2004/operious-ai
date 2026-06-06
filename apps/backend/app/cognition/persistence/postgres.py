"""Postgres cognition usage persistence."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.cognition.db.models import (
    CognitionAuditRecordRow,
    CognitionLLMUsageRow,
    CognitionSemanticRejectionRow,
)
from app.cognition.exceptions import CognitionPersistenceError
from app.cognition.identity import (
    CognitionAuditId,
    CognitionLLMUsageId,
    CognitionSemanticRejectionId,
)
from app.cognition.models import (
    CognitionAuditRecord,
    CognitionLLMUsageRecord,
    CognitionLLMUsageStatus,
    CognitionSemanticRejectionDirection,
    CognitionSemanticRejectionRecord,
)
from app.data_protection.crypto import DataProtectionService
from app.repositories.base import BaseRepository
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.db.models import TenantRow


class PostgresCognitionUsagePersistence(BaseRepository):
    """Postgres-backed tenant usage ledger."""

    __slots__ = ("_audit_encryptor", "_data_protection")

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit_encryptor: TenantCredentialEncryptor | None = None,
        data_protection: DataProtectionService | None = None,
    ) -> None:
        super().__init__(session)
        self._audit_encryptor = audit_encryptor
        self._data_protection = data_protection

    async def save_llm_usage(
        self,
        record: CognitionLLMUsageRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_tenant(record.tenant_id, expected_tenant_id)
        metadata_json = await self._encrypt_usage_metadata(record)
        await self.session.merge(TenantRow(tenant_id=expected_tenant_id))
        try:
            async with self.session.begin_nested():
                existing = await self._usage_row(
                    record.usage_id,
                    expected_tenant_id=expected_tenant_id,
                )
                if existing is None:
                    self.session.add(
                        _record_to_row(record, metadata_json=metadata_json)
                    )
                else:
                    _update_row(existing, record, metadata_json=metadata_json)
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
        return None if row is None else await self._usage_row_to_record(row)

    async def save_cognition_audit(
        self,
        record: CognitionAuditRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_tenant(record.tenant_id, expected_tenant_id)
        prompt_full = await self._encrypt_audit_text(record, field="prompt_full")
        completion_full = await self._encrypt_audit_text(
            record,
            field="completion_full",
        )
        await self.session.merge(TenantRow(tenant_id=expected_tenant_id))
        try:
            async with self.session.begin_nested():
                existing = await self._audit_row(
                    record.audit_id,
                    expected_tenant_id=expected_tenant_id,
                )
                if existing is None:
                    self.session.add(
                        _audit_record_to_row(
                            record,
                            prompt_full=prompt_full,
                            completion_full=completion_full,
                        )
                    )
                else:
                    _update_audit_row(
                        existing,
                        record,
                        prompt_full=prompt_full,
                        completion_full=completion_full,
                    )
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
        return await self._audit_row_to_record(row)

    async def save_semantic_rejection(
        self,
        record: CognitionSemanticRejectionRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_tenant(record.tenant_id, expected_tenant_id)
        completion_excerpt = await self._encrypt_semantic_excerpt(record)
        metadata_json = await self._encrypt_semantic_metadata(record)
        await self.session.merge(TenantRow(tenant_id=expected_tenant_id))
        try:
            async with self.session.begin_nested():
                existing = await self._semantic_rejection_row(
                    record.rejection_id,
                    expected_tenant_id=expected_tenant_id,
                )
                if existing is None:
                    self.session.add(
                        _semantic_rejection_record_to_row(
                            record,
                            completion_excerpt=completion_excerpt,
                            metadata_json=metadata_json,
                        )
                    )
                else:
                    _update_semantic_rejection_row(
                        existing,
                        record,
                        completion_excerpt=completion_excerpt,
                        metadata_json=metadata_json,
                    )
        except IntegrityError as exc:
            raise CognitionPersistenceError(
                f"semantic rejection {record.rejection_id!s} could not be persisted"
            ) from exc

    async def get_semantic_rejection(
        self,
        rejection_id: CognitionSemanticRejectionId,
        *,
        expected_tenant_id: str,
    ) -> CognitionSemanticRejectionRecord | None:
        row = await self._semantic_rejection_row(
            rejection_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else await self._semantic_rejection_row_to_record(row)

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

    async def _semantic_rejection_row(
        self,
        rejection_id: CognitionSemanticRejectionId,
        *,
        expected_tenant_id: str,
    ) -> CognitionSemanticRejectionRow | None:
        stmt = select(CognitionSemanticRejectionRow).where(
            CognitionSemanticRejectionRow.rejection_id == rejection_id,
            CognitionSemanticRejectionRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _require_audit_encryptor(self) -> TenantCredentialEncryptor:
        if self._audit_encryptor is None:
            raise CognitionPersistenceError(
                "cognition audit encryption is not configured"
            )
        return self._audit_encryptor

    async def _encrypt_usage_metadata(
        self,
        record: CognitionLLMUsageRecord,
    ) -> dict[str, Any]:
        metadata = dict(record.metadata)
        if self._data_protection is None:
            return metadata
        return await self._data_protection.encrypt_json_values(
            metadata,
            tenant_id=record.tenant_id,
            subject_id=record.session_id,
            field="cognition_llm_usage.metadata_json",
        )

    async def _usage_row_to_record(
        self,
        row: CognitionLLMUsageRow,
    ) -> CognitionLLMUsageRecord:
        record = _row_to_record(row)
        if self._data_protection is None:
            return record
        metadata = await self._data_protection.decrypt_json_values(record.metadata)
        return CognitionLLMUsageRecord(
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
            status=record.status,
            created_at=record.created_at,
            metadata=metadata,
        )

    async def _encrypt_semantic_excerpt(
        self,
        record: CognitionSemanticRejectionRecord,
    ) -> str:
        if self._data_protection is None:
            return record.completion_excerpt
        return await self._data_protection.encrypt_text(
            record.completion_excerpt,
            tenant_id=record.tenant_id,
            subject_id=record.session_id,
            field="cognition_semantic_rejection_records.completion_excerpt",
        )

    async def _decrypt_semantic_excerpt(
        self,
        row: CognitionSemanticRejectionRow,
    ) -> str:
        if self._data_protection is None:
            return row.completion_excerpt
        return await self._data_protection.decrypt_text(row.completion_excerpt)

    async def _encrypt_semantic_metadata(
        self,
        record: CognitionSemanticRejectionRecord,
    ) -> dict[str, Any]:
        metadata = dict(record.metadata)
        if self._data_protection is None:
            return metadata
        return await self._data_protection.encrypt_json_values(
            metadata,
            tenant_id=record.tenant_id,
            subject_id=record.session_id,
            field="cognition_semantic_rejection_records.metadata_json",
        )

    async def _semantic_rejection_row_to_record(
        self,
        row: CognitionSemanticRejectionRow,
    ) -> CognitionSemanticRejectionRecord:
        metadata = _as_dict(row.metadata_json)
        if self._data_protection is not None:
            metadata = await self._data_protection.decrypt_json_values(metadata)
        return CognitionSemanticRejectionRecord(
            rejection_id=CognitionSemanticRejectionId(row.rejection_id),
            tenant_id=row.tenant_id,
            execution_id=row.execution_id,
            dispatch_id=row.dispatch_id,
            session_id=row.session_id,
            provider=row.provider,
            model=row.model,
            canonical_terms=tuple(_as_str_list(row.canonical_terms)),
            allowed_terms=tuple(_as_str_list(row.allowed_terms)),
            output_terms=tuple(_as_str_list(row.output_terms)),
            missing_terms=tuple(_as_str_list(row.missing_terms)),
            introduced_terms=tuple(_as_str_list(row.introduced_terms)),
            direction=CognitionSemanticRejectionDirection(row.direction),
            completion_sha256=row.completion_sha256,
            completion_excerpt=await self._decrypt_semantic_excerpt(row),
            completion_excerpt_sha256=row.completion_excerpt_sha256,
            created_at=row.created_at,
            attempt_id=row.attempt_id,
            attempt_number=row.attempt_number,
            usage_id=(
                CognitionLLMUsageId(row.usage_id)
                if row.usage_id is not None
                else None
            ),
            audit_id=(
                CognitionAuditId(row.audit_id)
                if row.audit_id is not None
                else None
            ),
            metadata=metadata,
        )

    async def _encrypt_audit_text(
        self,
        record: CognitionAuditRecord,
        *,
        field: str,
    ) -> bytes:
        value = record.prompt_full if field == "prompt_full" else record.completion_full
        if self._data_protection is not None:
            return await self._data_protection.encrypt_bytes(
                value.encode("utf-8"),
                tenant_id=record.tenant_id,
                subject_id=record.subject_id or record.execution_id,
                field=f"cognition_audit_records.{field}",
            )
        return _encrypt_text(
            self._require_audit_encryptor(),
            tenant_id=record.tenant_id,
            key=field,
            value=value,
        )

    async def _decrypt_audit_text(
        self,
        *,
        row: CognitionAuditRecordRow,
        field: str,
        encrypted: bytes,
    ) -> str:
        decrypted = encrypted
        if self._data_protection is not None:
            decrypted = await self._data_protection.decrypt_bytes(encrypted)
            if decrypted != encrypted:
                return decrypted.decode("utf-8")
        if self._audit_encryptor is not None:
            return _decrypt_text(
                self._audit_encryptor,
                tenant_id=row.tenant_id,
                key=field,
                encrypted=encrypted,
            )
        raise CognitionPersistenceError(
            "cognition audit row is not envelope-encrypted and no legacy "
            "audit encryptor is configured"
        )

    async def _audit_row_to_record(
        self,
        row: CognitionAuditRecordRow,
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
            prompt_full=await self._decrypt_audit_text(
                row=row,
                field="prompt_full",
                encrypted=row.prompt_full,
            ),
            completion_full=await self._decrypt_audit_text(
                row=row,
                field="completion_full",
                encrypted=row.completion_full,
            ),
            prompt_sha256=row.prompt_sha256,
            completion_sha256=row.completion_sha256,
            model_name=row.model_name,
            token_usage=_as_dict(row.token_usage),
            captured_at=row.captured_at,
            subject_id=row.execution_id,
        )


def _record_to_row(
    record: CognitionLLMUsageRecord,
    *,
    metadata_json: dict[str, Any] | None = None,
) -> CognitionLLMUsageRow:
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
        metadata_json=dict(record.metadata) if metadata_json is None else metadata_json,
    )


def _update_row(
    row: CognitionLLMUsageRow,
    record: CognitionLLMUsageRecord,
    *,
    metadata_json: dict[str, Any] | None = None,
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
    row.metadata_json = dict(record.metadata) if metadata_json is None else metadata_json


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
    *,
    prompt_full: bytes,
    completion_full: bytes,
) -> CognitionAuditRecordRow:
    return CognitionAuditRecordRow(
        audit_id=record.audit_id,
        tenant_id=record.tenant_id,
        execution_id=record.execution_id,
        usage_id=record.usage_id,
        prompt_full=prompt_full,
        completion_full=completion_full,
        prompt_sha256=record.prompt_sha256,
        completion_sha256=record.completion_sha256,
        model_name=record.model_name,
        token_usage=dict(record.token_usage),
        captured_at=record.captured_at,
    )


def _update_audit_row(
    row: CognitionAuditRecordRow,
    record: CognitionAuditRecord,
    *,
    prompt_full: bytes,
    completion_full: bytes,
) -> None:
    row.execution_id = record.execution_id
    row.usage_id = record.usage_id
    row.prompt_full = prompt_full
    row.completion_full = completion_full
    row.prompt_sha256 = record.prompt_sha256
    row.completion_sha256 = record.completion_sha256
    row.model_name = record.model_name
    row.token_usage = dict(record.token_usage)
    row.captured_at = record.captured_at


def _semantic_rejection_record_to_row(
    record: CognitionSemanticRejectionRecord,
    *,
    completion_excerpt: str,
    metadata_json: dict[str, Any],
) -> CognitionSemanticRejectionRow:
    return CognitionSemanticRejectionRow(
        rejection_id=record.rejection_id,
        tenant_id=record.tenant_id,
        execution_id=record.execution_id,
        dispatch_id=record.dispatch_id,
        session_id=record.session_id,
        attempt_id=record.attempt_id,
        attempt_number=record.attempt_number,
        usage_id=record.usage_id,
        audit_id=record.audit_id,
        provider=record.provider,
        model=record.model,
        canonical_terms=list(record.canonical_terms),
        allowed_terms=list(record.allowed_terms),
        output_terms=list(record.output_terms),
        missing_terms=list(record.missing_terms),
        introduced_terms=list(record.introduced_terms),
        direction=record.direction.value,
        completion_sha256=record.completion_sha256,
        completion_excerpt=completion_excerpt,
        completion_excerpt_sha256=record.completion_excerpt_sha256,
        created_at=record.created_at,
        metadata_json=metadata_json,
    )


def _update_semantic_rejection_row(
    row: CognitionSemanticRejectionRow,
    record: CognitionSemanticRejectionRecord,
    *,
    completion_excerpt: str,
    metadata_json: dict[str, Any],
) -> None:
    row.execution_id = record.execution_id
    row.dispatch_id = record.dispatch_id
    row.session_id = record.session_id
    row.attempt_id = record.attempt_id
    row.attempt_number = record.attempt_number
    row.usage_id = record.usage_id
    row.audit_id = record.audit_id
    row.provider = record.provider
    row.model = record.model
    row.canonical_terms = list(record.canonical_terms)
    row.allowed_terms = list(record.allowed_terms)
    row.output_terms = list(record.output_terms)
    row.missing_terms = list(record.missing_terms)
    row.introduced_terms = list(record.introduced_terms)
    row.direction = record.direction.value
    row.completion_sha256 = record.completion_sha256
    row.completion_excerpt = completion_excerpt
    row.completion_excerpt_sha256 = record.completion_excerpt_sha256
    row.created_at = record.created_at
    row.metadata_json = metadata_json


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


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [str(item) for item in items]


__all__ = ["PostgresCognitionUsagePersistence"]
