"""In-memory tenant configuration persistence."""

from __future__ import annotations

import asyncio

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


class InMemoryTenantConfigurationRepository:
    """Tenant-clamped in-memory repository for tests."""

    __slots__ = ("_channels", "_documents", "_policies", "_lock")

    def __init__(self) -> None:
        self._channels: dict[
            TenantChannelConfigurationId,
            TenantChannelConfigurationRecord,
        ] = {}
        self._documents: dict[
            TenantKnowledgeDocumentId,
            TenantKnowledgeDocumentRecord,
        ] = {}
        self._policies: dict[
            TenantGovernancePolicyId,
            TenantGovernancePolicyRecord,
        ] = {}
        self._lock = asyncio.Lock()

    async def save_channel_configuration(
        self,
        record: TenantChannelConfigurationRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_write_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            self._channels[record.config_id] = record

    async def get_channel_configuration(
        self,
        config_id: TenantChannelConfigurationId,
        *,
        expected_tenant_id: str,
    ) -> TenantChannelConfigurationRecord | None:
        record = self._channels.get(config_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_channel_configurations(
        self,
        query: TenantChannelConfigurationQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantChannelConfigurationPage:
        rows = [
            r for r in self._channels.values()
            if r.tenant_id == expected_tenant_id
        ]
        if query.config_id is not None:
            rows = [r for r in rows if r.config_id == query.config_id]
        if query.channel_type is not None:
            rows = [
                r for r in rows if r.channel_type == query.channel_type
            ]
        if query.status is not None:
            rows = [r for r in rows if r.status == query.status]
        rows.sort(key=lambda r: (r.channel_type.value, r.routing_address))
        return _channel_page(rows, query.limit, query.offset)

    async def resolve_channel_configuration(
        self,
        *,
        channel_type: str,
        routing_address: str,
    ) -> TenantChannelConfigurationRecord | None:
        matches = [
            r
            for r in self._channels.values()
            if r.channel_type.value == channel_type
            and r.routing_address == routing_address
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    async def save_knowledge_document(
        self,
        record: TenantKnowledgeDocumentRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_write_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            self._documents[record.document_id] = record

    async def get_knowledge_document(
        self,
        document_id: TenantKnowledgeDocumentId,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentRecord | None:
        record = self._documents.get(document_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_knowledge_documents(
        self,
        query: TenantKnowledgeDocumentQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentPage:
        rows = [
            r for r in self._documents.values()
            if r.tenant_id == expected_tenant_id
        ]
        if query.document_id is not None:
            rows = [r for r in rows if r.document_id == query.document_id]
        if query.document_type is not None:
            rows = [
                r for r in rows if r.document_type == query.document_type
            ]
        if query.status is not None:
            rows = [r for r in rows if r.status == query.status]
        rows.sort(key=lambda r: (r.document_type.value, r.title))
        return _document_page(rows, query.limit, query.offset)

    async def save_governance_policy(
        self,
        record: TenantGovernancePolicyRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_write_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            self._policies[record.policy_id] = record

    async def get_governance_policy(
        self,
        policy_id: TenantGovernancePolicyId,
        *,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyRecord | None:
        record = self._policies.get(policy_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_governance_policies(
        self,
        query: TenantGovernancePolicyQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyPage:
        rows = [
            r for r in self._policies.values()
            if r.tenant_id == expected_tenant_id
        ]
        if query.policy_id is not None:
            rows = [r for r in rows if r.policy_id == query.policy_id]
        if query.policy_type is not None:
            rows = [r for r in rows if r.policy_type == query.policy_type]
        if query.status is not None:
            rows = [r for r in rows if r.status == query.status]
        rows.sort(key=lambda r: (r.policy_type, str(r.policy_id)))
        return _policy_page(rows, query.limit, query.offset)


def _assert_write_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise TenantConfigurationPersistenceError(
            "record tenant_id does not match expected_tenant_id"
        )


def _channel_page(
    rows: list[TenantChannelConfigurationRecord],
    limit: int | None,
    offset: int,
) -> TenantChannelConfigurationPage:
    total = len(rows)
    sliced = rows[offset:]
    if limit is not None:
        sliced = sliced[:limit]
    return TenantChannelConfigurationPage(
        items=tuple(sliced), total=total, offset=offset
    )


def _document_page(
    rows: list[TenantKnowledgeDocumentRecord],
    limit: int | None,
    offset: int,
) -> TenantKnowledgeDocumentPage:
    total = len(rows)
    sliced = rows[offset:]
    if limit is not None:
        sliced = sliced[:limit]
    return TenantKnowledgeDocumentPage(
        items=tuple(sliced), total=total, offset=offset
    )


def _policy_page(
    rows: list[TenantGovernancePolicyRecord],
    limit: int | None,
    offset: int,
) -> TenantGovernancePolicyPage:
    total = len(rows)
    sliced = rows[offset:]
    if limit is not None:
        sliced = sliced[:limit]
    return TenantGovernancePolicyPage(
        items=tuple(sliced), total=total, offset=offset
    )


__all__ = ["InMemoryTenantConfigurationRepository"]
