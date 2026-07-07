"""Per-connector credential persistence and runtime.

Provides OPCRED2-encrypted credential storage scoped by (tenant_id, connector_id)
for custom connectors that are NOT backed by a TenantChannelType enum entry.
Decoupled from the channel credential table so non-commerce verticals
(banking, telecom, etc.) can carry their own auth without needing an OMS
or WhatsApp channel row.

Encryption reuses TenantCredentialEnvelopeEncryptor (OPCRED2 AES-256-GCM).
The channel_type passed to the encryptor is the literal connector_id string
so the AAD is bound to this specific connector, not a generic channel label.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenant.db.models import ConnectorCredentialRow, TenantRow

logger = logging.getLogger(__name__)

ConnectorCredentialStatus = Literal["pending_validation", "active", "disabled"]


@dataclass(frozen=True, slots=True)
class ConnectorCredentialRecord:
    tenant_id: str
    connector_id: str
    credentials_enc: bytes
    credential_hash: str
    status: ConnectorCredentialStatus
    configured_by: str
    source_approval_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectorCredentialCodec(Protocol):
    """Encrypt / decrypt connector credentials using OPCRED2 envelope."""

    def encrypt(
        self,
        *,
        tenant_id: str,
        credentials: dict[str, Any],
        channel_type: str,
    ) -> bytes: ...

    def decrypt(
        self,
        *,
        tenant_id: str,
        encrypted_credentials: bytes,
        channel_type: str,
    ) -> dict[str, Any]: ...


class ConnectorCredentialRepository:
    """Postgres-backed per-connector credential store."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        expected_tenant_id: str,
    ) -> ConnectorCredentialRecord | None:
        if tenant_id != expected_tenant_id:
            return None
        stmt = select(ConnectorCredentialRow).where(
            ConnectorCredentialRow.tenant_id == expected_tenant_id,
            ConnectorCredentialRow.connector_id == connector_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def get_active(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        expected_tenant_id: str,
    ) -> ConnectorCredentialRecord | None:
        record = await self.get(
            tenant_id=tenant_id,
            connector_id=connector_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None or record.status != "active":
            return None
        return record

    async def upsert(
        self,
        record: ConnectorCredentialRecord,
        *,
        expected_tenant_id: str,
    ) -> ConnectorCredentialRecord:
        if record.tenant_id != expected_tenant_id:
            raise ValueError("connector credential tenant does not match expected tenant")
        await self._session.merge(TenantRow(tenant_id=expected_tenant_id))
        existing = await self._row(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
        )
        now = _utcnow()
        if existing is None:
            row = ConnectorCredentialRow(
                tenant_id=record.tenant_id,
                connector_id=record.connector_id,
                credentials_enc=record.credentials_enc,
                credential_hash=record.credential_hash,
                status=record.status,
                configured_by=record.configured_by,
                source_approval_id=record.source_approval_id,
                created_at=record.created_at or now,
                updated_at=record.updated_at or now,
            )
            self._session.add(row)
        else:
            existing.credentials_enc = record.credentials_enc
            existing.credential_hash = record.credential_hash
            existing.status = record.status
            existing.configured_by = record.configured_by
            existing.source_approval_id = record.source_approval_id
            existing.updated_at = now
        await self._session.flush()
        updated = await self._row(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
        )
        return record if updated is None else _row_to_record(updated)

    async def list_active_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[ConnectorCredentialRecord]:
        if tenant_id != expected_tenant_id:
            return []
        stmt = select(ConnectorCredentialRow).where(
            ConnectorCredentialRow.tenant_id == expected_tenant_id,
            ConnectorCredentialRow.status == "active",
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_row_to_record(row) for row in rows]

    async def _row(
        self,
        *,
        tenant_id: str,
        connector_id: str,
    ) -> ConnectorCredentialRow | None:
        stmt = select(ConnectorCredentialRow).where(
            ConnectorCredentialRow.tenant_id == tenant_id,
            ConnectorCredentialRow.connector_id == connector_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class ConnectorScopedCredentialRuntime:
    """Runtime that resolves connector credentials from ConnectorCredentialRepository.

    Used by build_tenant_action_tool_registry for custom (non-channel) connectors.
    Falls back to loading raw decrypted credentials so GenericConnectorTool.invoke()
    can call connector_auth_headers() and build the Authorization header.
    """

    def __init__(
        self,
        *,
        repository: ConnectorCredentialRepository,
        codec: ConnectorCredentialCodec,
        tenant_id: str,
    ) -> None:
        self._repository = repository
        self._codec = codec
        self._tenant_id = tenant_id

    async def load_connector_credentials(
        self,
        *,
        tenant_id: str,
        connector_id: str,
    ) -> dict[str, Any]:
        if tenant_id != self._tenant_id:
            raise PermissionError(
                "connector credential tenant does not match runtime tenant"
            )
        record = await self._repository.get_active(
            tenant_id=tenant_id,
            connector_id=connector_id,
            expected_tenant_id=tenant_id,
        )
        if record is None:
            raise KeyError(
                f"no active credential found for connector {connector_id!r}"
            )
        return self._codec.decrypt(
            tenant_id=tenant_id,
            encrypted_credentials=record.credentials_enc,
            channel_type=connector_id,
        )


def encrypt_connector_credentials(
    *,
    tenant_id: str,
    connector_id: str,
    credentials: dict[str, Any],
    codec: ConnectorCredentialCodec,
) -> tuple[bytes, str]:
    """Encrypt credentials and return (ciphertext, sha256_hex).

    The SHA-256 hex is stored in the change-request sentinel.
    """
    ciphertext = codec.encrypt(
        tenant_id=tenant_id,
        credentials=credentials,
        channel_type=connector_id,
    )
    credential_hash = hashlib.sha256(ciphertext).hexdigest()
    return ciphertext, credential_hash


def _row_to_record(row: ConnectorCredentialRow) -> ConnectorCredentialRecord:
    return ConnectorCredentialRecord(
        tenant_id=row.tenant_id,
        connector_id=row.connector_id,
        credentials_enc=row.credentials_enc,
        credential_hash=row.credential_hash,
        status=row.status,  # type: ignore[arg-type]
        configured_by=row.configured_by,
        source_approval_id=row.source_approval_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ConnectorCredentialCodec",
    "ConnectorCredentialRecord",
    "ConnectorCredentialRepository",
    "ConnectorCredentialStatus",
    "ConnectorScopedCredentialRuntime",
    "encrypt_connector_credentials",
]
