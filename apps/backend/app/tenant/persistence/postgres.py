"""Postgres tenant configuration repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.tenant.db.models import (
    TenantChannelConfigurationRow,
    TenantGovernancePolicyRow,
    TenantKnowledgeDocumentRow,
    TenantRow,
)
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.exceptions import TenantConfigurationPersistenceError
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
)
from app.tenant.persistence.models import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
    TenantGovernancePolicyPage,
    TenantGovernancePolicyQuery,
    TenantKnowledgeDocumentPage,
    TenantKnowledgeDocumentQuery,
)
from app.tenant.persistence.records import (
    TenantChannelConfigurationRecord,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
)


class PostgresTenantConfigurationRepository(BaseRepository):
    """Postgres-backed tenant-owned configuration repository."""

    async def save_channel_configuration(
        self,
        record: TenantChannelConfigurationRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_write_tenant(record.tenant_id, expected_tenant_id)
        await self._ensure_tenant(expected_tenant_id)
        existing = await self._channel_row(
            record.config_id, expected_tenant_id=expected_tenant_id
        )
        try:
            async with self.session.begin_nested():
                if existing is None:
                    self.session.add(_channel_record_to_row(record))
                else:
                    _update_channel_row(existing, record)
        except IntegrityError as exc:
            raise TenantConfigurationPersistenceError(
                "channel configuration could not be persisted"
            ) from exc

    async def get_channel_configuration(
        self,
        config_id: TenantChannelConfigurationId,
        *,
        expected_tenant_id: str,
    ) -> TenantChannelConfigurationRecord | None:
        row = await self._channel_row(
            config_id, expected_tenant_id=expected_tenant_id
        )
        return None if row is None else _channel_row_to_record(row)

    async def list_channel_configurations(
        self,
        query: TenantChannelConfigurationQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantChannelConfigurationPage:
        stmt = select(TenantChannelConfigurationRow).where(
            TenantChannelConfigurationRow.tenant_id == expected_tenant_id
        )
        if query.config_id is not None:
            stmt = stmt.where(
                TenantChannelConfigurationRow.config_id == query.config_id
            )
        if query.channel_type is not None:
            stmt = stmt.where(
                TenantChannelConfigurationRow.channel_type
                == query.channel_type.value
            )
        if query.status is not None:
            stmt = stmt.where(
                TenantChannelConfigurationRow.status == query.status.value
            )
        stmt = stmt.order_by(
            TenantChannelConfigurationRow.channel_type,
            TenantChannelConfigurationRow.routing_address,
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = len(rows)
        sliced = rows[query.offset :]
        if query.limit is not None:
            sliced = sliced[: query.limit]
        return TenantChannelConfigurationPage(
            items=tuple(_channel_row_to_record(row) for row in sliced),
            total=total,
            offset=query.offset,
        )

    async def resolve_channel_configuration(
        self,
        *,
        channel_type: str,
        routing_address: str,
    ) -> TenantChannelConfigurationRecord | None:
        stmt = (
            select(TenantChannelConfigurationRow)
            .where(
                TenantChannelConfigurationRow.channel_type == channel_type,
                TenantChannelConfigurationRow.routing_address == routing_address,
            )
            .limit(2)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        if len(rows) != 1:
            return None
        return _channel_row_to_record(rows[0])

    async def save_knowledge_document(
        self,
        record: TenantKnowledgeDocumentRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_write_tenant(record.tenant_id, expected_tenant_id)
        await self._ensure_tenant(expected_tenant_id)
        existing = await self._document_row(
            record.document_id, expected_tenant_id=expected_tenant_id
        )
        try:
            async with self.session.begin_nested():
                if existing is None:
                    self.session.add(_document_record_to_row(record))
                else:
                    _update_document_row(existing, record)
        except IntegrityError as exc:
            raise TenantConfigurationPersistenceError(
                "knowledge document could not be persisted"
            ) from exc

    async def get_knowledge_document(
        self,
        document_id: TenantKnowledgeDocumentId,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentRecord | None:
        row = await self._document_row(
            document_id, expected_tenant_id=expected_tenant_id
        )
        return None if row is None else _document_row_to_record(row)

    async def list_knowledge_documents(
        self,
        query: TenantKnowledgeDocumentQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentPage:
        stmt = select(TenantKnowledgeDocumentRow).where(
            TenantKnowledgeDocumentRow.tenant_id == expected_tenant_id
        )
        if query.document_id is not None:
            stmt = stmt.where(
                TenantKnowledgeDocumentRow.document_id == query.document_id
            )
        if query.document_type is not None:
            stmt = stmt.where(
                TenantKnowledgeDocumentRow.document_type
                == query.document_type.value
            )
        if query.status is not None:
            stmt = stmt.where(
                TenantKnowledgeDocumentRow.status == query.status.value
            )
        stmt = stmt.order_by(
            TenantKnowledgeDocumentRow.document_type,
            TenantKnowledgeDocumentRow.title,
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = len(rows)
        sliced = rows[query.offset :]
        if query.limit is not None:
            sliced = sliced[: query.limit]
        return TenantKnowledgeDocumentPage(
            items=tuple(_document_row_to_record(row) for row in sliced),
            total=total,
            offset=query.offset,
        )

    async def save_governance_policy(
        self,
        record: TenantGovernancePolicyRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_write_tenant(record.tenant_id, expected_tenant_id)
        await self._ensure_tenant(expected_tenant_id)
        existing = await self._policy_row(
            record.policy_id, expected_tenant_id=expected_tenant_id
        )
        try:
            async with self.session.begin_nested():
                if existing is None:
                    self.session.add(_policy_record_to_row(record))
                else:
                    _update_policy_row(existing, record)
        except IntegrityError as exc:
            raise TenantConfigurationPersistenceError(
                "governance policy could not be persisted"
            ) from exc

    async def get_governance_policy(
        self,
        policy_id: TenantGovernancePolicyId,
        *,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyRecord | None:
        row = await self._policy_row(
            policy_id, expected_tenant_id=expected_tenant_id
        )
        return None if row is None else _policy_row_to_record(row)

    async def list_governance_policies(
        self,
        query: TenantGovernancePolicyQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyPage:
        stmt = select(TenantGovernancePolicyRow).where(
            TenantGovernancePolicyRow.tenant_id == expected_tenant_id
        )
        if query.policy_id is not None:
            stmt = stmt.where(
                TenantGovernancePolicyRow.policy_id == query.policy_id
            )
        if query.policy_type is not None:
            stmt = stmt.where(
                TenantGovernancePolicyRow.policy_type == query.policy_type
            )
        if query.status is not None:
            stmt = stmt.where(
                TenantGovernancePolicyRow.status == query.status.value
            )
        stmt = stmt.order_by(
            TenantGovernancePolicyRow.policy_type,
            TenantGovernancePolicyRow.policy_id,
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = len(rows)
        sliced = rows[query.offset :]
        if query.limit is not None:
            sliced = sliced[: query.limit]
        return TenantGovernancePolicyPage(
            items=tuple(_policy_row_to_record(row) for row in sliced),
            total=total,
            offset=query.offset,
        )

    async def _ensure_tenant(self, tenant_id: str) -> None:
        await self.session.merge(TenantRow(tenant_id=tenant_id))

    async def _channel_row(
        self,
        config_id: TenantChannelConfigurationId,
        *,
        expected_tenant_id: str,
    ) -> TenantChannelConfigurationRow | None:
        stmt = select(TenantChannelConfigurationRow).where(
            TenantChannelConfigurationRow.config_id == config_id,
            TenantChannelConfigurationRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _document_row(
        self,
        document_id: TenantKnowledgeDocumentId,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentRow | None:
        stmt = select(TenantKnowledgeDocumentRow).where(
            TenantKnowledgeDocumentRow.document_id == document_id,
            TenantKnowledgeDocumentRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _policy_row(
        self,
        policy_id: TenantGovernancePolicyId,
        *,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyRow | None:
        stmt = select(TenantGovernancePolicyRow).where(
            TenantGovernancePolicyRow.policy_id == policy_id,
            TenantGovernancePolicyRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _assert_write_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise TenantConfigurationPersistenceError(
            "record tenant_id does not match expected_tenant_id"
        )


def _channel_record_to_row(
    record: TenantChannelConfigurationRecord,
) -> TenantChannelConfigurationRow:
    return TenantChannelConfigurationRow(
        config_id=record.config_id,
        tenant_id=record.tenant_id,
        channel_type=record.channel_type.value,
        status=record.status.value,
        routing_address=record.routing_address,
        credentials_enc=record.credentials_enc,
        webhook_secret=record.webhook_secret,
        verified_at=record.verified_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _update_channel_row(
    row: TenantChannelConfigurationRow,
    record: TenantChannelConfigurationRecord,
) -> None:
    row.channel_type = record.channel_type.value
    row.status = record.status.value
    row.routing_address = record.routing_address
    row.credentials_enc = record.credentials_enc
    row.webhook_secret = record.webhook_secret
    row.verified_at = record.verified_at
    row.created_at = record.created_at
    row.updated_at = record.updated_at


def _channel_row_to_record(
    row: TenantChannelConfigurationRow,
) -> TenantChannelConfigurationRecord:
    return TenantChannelConfigurationRecord(
        config_id=TenantChannelConfigurationId(row.config_id),
        tenant_id=row.tenant_id,
        channel_type=TenantChannelType(row.channel_type),
        status=TenantChannelStatus(row.status),
        routing_address=row.routing_address,
        credentials_enc=bytes(row.credentials_enc),
        webhook_secret=row.webhook_secret,
        verified_at=row.verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _document_record_to_row(
    record: TenantKnowledgeDocumentRecord,
) -> TenantKnowledgeDocumentRow:
    return TenantKnowledgeDocumentRow(
        document_id=record.document_id,
        tenant_id=record.tenant_id,
        title=record.title,
        content=record.content,
        document_type=record.document_type.value,
        status=record.status.value,
        version=record.version,
        uploaded_by=record.uploaded_by,
        vector_indexed_at=record.vector_indexed_at,
        created_at=record.created_at,
    )


def _update_document_row(
    row: TenantKnowledgeDocumentRow,
    record: TenantKnowledgeDocumentRecord,
) -> None:
    row.title = record.title
    row.content = record.content
    row.document_type = record.document_type.value
    row.status = record.status.value
    row.version = record.version
    row.uploaded_by = record.uploaded_by
    row.vector_indexed_at = record.vector_indexed_at
    row.created_at = record.created_at


def _document_row_to_record(
    row: TenantKnowledgeDocumentRow,
) -> TenantKnowledgeDocumentRecord:
    return TenantKnowledgeDocumentRecord(
        document_id=TenantKnowledgeDocumentId(row.document_id),
        tenant_id=row.tenant_id,
        title=row.title,
        content=row.content,
        document_type=TenantKnowledgeDocumentType(row.document_type),
        status=TenantKnowledgeDocumentStatus(row.status),
        version=row.version,
        uploaded_by=row.uploaded_by,
        vector_indexed_at=row.vector_indexed_at,
        created_at=row.created_at,
    )


def _policy_record_to_row(
    record: TenantGovernancePolicyRecord,
) -> TenantGovernancePolicyRow:
    return TenantGovernancePolicyRow(
        policy_id=record.policy_id,
        tenant_id=record.tenant_id,
        policy_type=record.policy_type,
        parameters=dict(record.parameters),
        status=record.status.value,
        version=record.version,
        approved_by=record.approved_by,
        effective_from=record.effective_from,
        created_at=record.created_at,
    )


def _update_policy_row(
    row: TenantGovernancePolicyRow,
    record: TenantGovernancePolicyRecord,
) -> None:
    row.policy_type = record.policy_type
    row.parameters = dict(record.parameters)
    row.status = record.status.value
    row.version = record.version
    row.approved_by = record.approved_by
    row.effective_from = record.effective_from
    row.created_at = record.created_at


def _policy_row_to_record(
    row: TenantGovernancePolicyRow,
) -> TenantGovernancePolicyRecord:
    return TenantGovernancePolicyRecord(
        policy_id=TenantGovernancePolicyId(row.policy_id),
        tenant_id=row.tenant_id,
        policy_type=row.policy_type,
        parameters=_as_dict(row.parameters),
        status=TenantGovernancePolicyStatus(row.status),
        version=row.version,
        approved_by=row.approved_by,
        effective_from=row.effective_from,
        created_at=row.created_at,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return {}


__all__ = ["PostgresTenantConfigurationRepository"]
