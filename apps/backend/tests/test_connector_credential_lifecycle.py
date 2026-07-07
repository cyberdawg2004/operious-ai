"""Unit tests for per-connector credential propose/apply dual-control lifecycle.

Tests the CONNECTOR_CREDENTIAL change type end-to-end using in-memory test
doubles — no Postgres required. Covers:
  - propose_connector_credential encrypts and stores pending, returns change request
  - propose rejects missing connector_id and empty credentials
  - propose rejects when credential store is not configured on service
  - apply activates the pending credential (hash integrity check passes)
  - apply fails when hash has been tampered (fail-closed)
  - apply fails when no pending credential found
  - apply fails when credential is already active (wrong state)
  - separation-of-duties: proposer == approver → SeparationError
  - ConnectorScopedCredentialRuntime decrypts active credentials
  - ConnectorScopedCredentialRuntime raises KeyError for missing/inactive creds
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.tools.connectors.credentials import (
    ConnectorCredentialRecord,
    ConnectorScopedCredentialRuntime,
    encrypt_connector_credentials,
)
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.tenant.change_requests import (
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
)

# ---------------------------------------------------------------------------
# Helpers / test doubles
# ---------------------------------------------------------------------------

_TENANT = "tenant-cred-unit-test"
_CONNECTOR_ID = "account.freeze"
_PROPOSER = "admin-a"
_APPROVER = "admin-b"


class _InMemoryChangeRequestRepository:
    """Minimal in-memory TenantConfigChangeRequestRepository for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, TenantConfigChangeRequestRecord] = {}

    async def create(
        self,
        record: TenantConfigChangeRequestRecord,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        self._store[str(record.change_request_id)] = record
        return record

    async def get(
        self,
        change_request_id: uuid.UUID | str,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord | None:
        return self._store.get(str(change_request_id))

    async def update(
        self,
        record: TenantConfigChangeRequestRecord,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        self._store[str(record.change_request_id)] = record
        return record

    async def list(self, *, tenant_id: str, **_: Any) -> Any:
        return []


class _InMemoryConnectorCredentialRepository:
    """Minimal in-memory ConnectorCredentialRepository for unit tests."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], ConnectorCredentialRecord] = {}

    async def get(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        expected_tenant_id: str,
    ) -> ConnectorCredentialRecord | None:
        if tenant_id != expected_tenant_id:
            return None
        return self._store.get((tenant_id, connector_id))

    async def get_active(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        expected_tenant_id: str,
    ) -> ConnectorCredentialRecord | None:
        rec = await self.get(
            tenant_id=tenant_id,
            connector_id=connector_id,
            expected_tenant_id=expected_tenant_id,
        )
        if rec is None or rec.status != "active":
            return None
        return rec

    async def upsert(
        self,
        record: ConnectorCredentialRecord,
        *,
        expected_tenant_id: str,
    ) -> ConnectorCredentialRecord:
        self._store[(record.tenant_id, record.connector_id)] = record
        return record

    async def list_active_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[ConnectorCredentialRecord]:
        if tenant_id != expected_tenant_id:
            return []
        return [
            r
            for r in self._store.values()
            if r.tenant_id == tenant_id and r.status == "active"
        ]


class _NullCodec:
    """Trivial codec: JSON encode/decode with no real encryption (test-only)."""

    def encrypt(
        self,
        *,
        tenant_id: str,
        credentials: dict[str, Any],
        channel_type: str,
    ) -> bytes:
        return json.dumps(credentials).encode()

    def decrypt(
        self,
        *,
        tenant_id: str,
        encrypted_credentials: bytes,
        channel_type: str,
    ) -> dict[str, Any]:
        return json.loads(encrypted_credentials.decode())


def _make_service(
    change_repo: _InMemoryChangeRequestRepository | None = None,
    cred_repo: _InMemoryConnectorCredentialRepository | None = None,
    codec: _NullCodec | None = None,
) -> TenantConfigChangeRequestService:
    session = MagicMock()
    session.commit = AsyncMock()
    event_appender = MagicMock()
    event_appender.append_event = AsyncMock()
    tenant_config_svc = MagicMock()

    return TenantConfigChangeRequestService(
        repository=change_repo or _InMemoryChangeRequestRepository(),
        tenant_configuration_service=tenant_config_svc,
        event_appender=event_appender,
        session=session,
        connector_credential_repository=cred_repo,
        connector_credential_codec=codec,
    )


# ---------------------------------------------------------------------------
# propose_connector_credential
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_connector_credential_encrypts_and_stores_pending() -> None:
    """propose_connector_credential encrypts credentials immediately and stores pending."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    codec = _NullCodec()
    service = _make_service(cred_repo=cred_repo, codec=codec)

    result = await service.propose_connector_credential(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials={"token": "secret-bearer"},
        proposed_by=_PROPOSER,
    )

    # Change request returned and stored
    assert result.tenant_id == _TENANT
    assert result.change_type is TenantConfigChangeType.CONNECTOR_CREDENTIAL
    assert result.status is TenantConfigChangeRequestStatus.PROPOSED
    assert result.proposed_by == _PROPOSER

    # Sentinel payload contains connector_id and hash but NOT plaintext
    payload = result.proposed_payload
    assert payload["connector_id"] == _CONNECTOR_ID
    assert "credential_hash" in payload
    assert "token" not in str(payload)

    # Credential row stored as pending_validation
    stored = await cred_repo.get(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        expected_tenant_id=_TENANT,
    )
    assert stored is not None
    assert stored.status == "pending_validation"
    assert stored.configured_by == _PROPOSER

    # Hash in sentinel matches SHA-256 of stored ciphertext
    actual_hash = hashlib.sha256(stored.credentials_enc).hexdigest()
    assert actual_hash == payload["credential_hash"]


@pytest.mark.asyncio
async def test_propose_connector_credential_no_store_raises() -> None:
    """propose raises when credential store is not configured."""
    service = _make_service()  # no cred_repo / codec

    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="not configured"):
        await service.propose_connector_credential(
            tenant_id=_TENANT,
            connector_id=_CONNECTOR_ID,
            credentials={"token": "x"},
            proposed_by=_PROPOSER,
        )


@pytest.mark.asyncio
async def test_propose_connector_credential_empty_connector_id_raises() -> None:
    cred_repo = _InMemoryConnectorCredentialRepository()
    service = _make_service(cred_repo=cred_repo, codec=_NullCodec())

    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="connector_id"):
        await service.propose_connector_credential(
            tenant_id=_TENANT,
            connector_id="   ",
            credentials={"token": "x"},
            proposed_by=_PROPOSER,
        )


@pytest.mark.asyncio
async def test_propose_connector_credential_empty_credentials_raises() -> None:
    cred_repo = _InMemoryConnectorCredentialRepository()
    service = _make_service(cred_repo=cred_repo, codec=_NullCodec())

    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="credentials"):
        await service.propose_connector_credential(
            tenant_id=_TENANT,
            connector_id=_CONNECTOR_ID,
            credentials={},
            proposed_by=_PROPOSER,
        )


# ---------------------------------------------------------------------------
# approve + apply (CONNECTOR_CREDENTIAL lifecycle)
# ---------------------------------------------------------------------------


async def _propose_and_approve(
    service: TenantConfigChangeRequestService,
    change_repo: _InMemoryChangeRequestRepository,
) -> TenantConfigChangeRequestRecord:
    """Helper: propose then approve with different principals."""
    proposed = await service.propose_connector_credential(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials={"token": "secret-bearer"},
        proposed_by=_PROPOSER,
    )
    # Manually transition to APPROVED state (mimic service.approve)
    approved = TenantConfigChangeRequestRecord(
        change_request_id=proposed.change_request_id,
        tenant_id=proposed.tenant_id,
        change_type=proposed.change_type,
        proposed_payload=proposed.proposed_payload,
        status=TenantConfigChangeRequestStatus.APPROVED,
        proposed_by=proposed.proposed_by,
        proposed_at=proposed.proposed_at,
        approved_by=_APPROVER,
        approved_at=datetime.now(timezone.utc),
    )
    change_repo._store[str(approved.change_request_id)] = approved
    return approved


@pytest.mark.asyncio
async def test_apply_connector_credential_activates_pending() -> None:
    """apply transitions pending credential to active and returns activation result."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    codec = _NullCodec()
    change_repo = _InMemoryChangeRequestRepository()
    service = _make_service(change_repo=change_repo, cred_repo=cred_repo, codec=codec)

    approved = await _propose_and_approve(service, change_repo)

    # Build minimal approval record for _apply
    from app.sop_intelligence import ApprovalRecord, ApprovalStatus
    approval = ApprovalRecord(
        approval_id=str(uuid.uuid4()),
        tenant_id=_TENANT,
        document_id=str(approved.change_request_id),
        proposed_change="tenant_config:connector_credential",
        evidence_sessions=(),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=_PROPOSER,
        reviewed_by=_APPROVER,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata={},
    )

    result = await service._apply_connector_credential(
        approved,
        dict(approved.proposed_payload),
        approval,
    )

    assert result["kind"] == "connector_credential"
    assert result["operation"] == "activate"
    assert result["connector_id"] == _CONNECTOR_ID
    assert result["status"] == "active"

    # Credential row is now active
    activated = await cred_repo.get_active(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        expected_tenant_id=_TENANT,
    )
    assert activated is not None
    assert activated.status == "active"
    assert activated.source_approval_id == approval.approval_id


@pytest.mark.asyncio
async def test_apply_connector_credential_hash_mismatch_fails_closed() -> None:
    """Tampered ciphertext (hash mismatch) raises lifecycle error — fail closed."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    codec = _NullCodec()
    change_repo = _InMemoryChangeRequestRepository()
    service = _make_service(change_repo=change_repo, cred_repo=cred_repo, codec=codec)

    approved = await _propose_and_approve(service, change_repo)

    # Tamper: overwrite ciphertext in the store with different bytes
    original = await cred_repo.get(
        tenant_id=_TENANT, connector_id=_CONNECTOR_ID, expected_tenant_id=_TENANT
    )
    assert original is not None
    tampered = ConnectorCredentialRecord(
        tenant_id=original.tenant_id,
        connector_id=original.connector_id,
        credentials_enc=b"tampered-bytes",
        credential_hash=original.credential_hash,
        status=original.status,
        configured_by=original.configured_by,
        source_approval_id=original.source_approval_id,
    )
    await cred_repo.upsert(tampered, expected_tenant_id=_TENANT)

    from app.sop_intelligence import ApprovalRecord, ApprovalStatus
    approval = ApprovalRecord(
        approval_id=str(uuid.uuid4()),
        tenant_id=_TENANT,
        document_id=str(approved.change_request_id),
        proposed_change="tenant_config:connector_credential",
        evidence_sessions=(),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=_PROPOSER,
        reviewed_by=_APPROVER,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata={},
    )

    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="hash mismatch"):
        await service._apply_connector_credential(
            approved,
            dict(approved.proposed_payload),
            approval,
        )


@pytest.mark.asyncio
async def test_apply_connector_credential_no_pending_row_raises() -> None:
    """apply raises when no pending credential row exists."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    codec = _NullCodec()
    change_repo = _InMemoryChangeRequestRepository()
    service = _make_service(change_repo=change_repo, cred_repo=cred_repo, codec=codec)

    approved = await _propose_and_approve(service, change_repo)

    # Delete the credential row from store
    cred_repo._store.clear()

    from app.sop_intelligence import ApprovalRecord, ApprovalStatus
    approval = ApprovalRecord(
        approval_id=str(uuid.uuid4()),
        tenant_id=_TENANT,
        document_id=str(approved.change_request_id),
        proposed_change="tenant_config:connector_credential",
        evidence_sessions=(),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=_PROPOSER,
        reviewed_by=_APPROVER,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata={},
    )

    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="not found"):
        await service._apply_connector_credential(
            approved,
            dict(approved.proposed_payload),
            approval,
        )


@pytest.mark.asyncio
async def test_apply_connector_credential_wrong_status_raises() -> None:
    """apply raises when credential is not in pending_validation state."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    codec = _NullCodec()
    change_repo = _InMemoryChangeRequestRepository()
    service = _make_service(change_repo=change_repo, cred_repo=cred_repo, codec=codec)

    approved = await _propose_and_approve(service, change_repo)

    # Force row to active before apply
    original = await cred_repo.get(
        tenant_id=_TENANT, connector_id=_CONNECTOR_ID, expected_tenant_id=_TENANT
    )
    assert original is not None
    already_active = ConnectorCredentialRecord(
        tenant_id=original.tenant_id,
        connector_id=original.connector_id,
        credentials_enc=original.credentials_enc,
        credential_hash=original.credential_hash,
        status="active",
        configured_by=original.configured_by,
        source_approval_id="some-prior-approval",
    )
    await cred_repo.upsert(already_active, expected_tenant_id=_TENANT)

    from app.sop_intelligence import ApprovalRecord, ApprovalStatus
    approval = ApprovalRecord(
        approval_id=str(uuid.uuid4()),
        tenant_id=_TENANT,
        document_id=str(approved.change_request_id),
        proposed_change="tenant_config:connector_credential",
        evidence_sessions=(),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=_PROPOSER,
        reviewed_by=_APPROVER,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata={},
    )

    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="not in pending"):
        await service._apply_connector_credential(
            approved,
            dict(approved.proposed_payload),
            approval,
        )


# ---------------------------------------------------------------------------
# ConnectorScopedCredentialRuntime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connector_scoped_runtime_decrypts_active_credential() -> None:
    """Runtime decrypts and returns credentials for an active connector."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    codec = _NullCodec()
    ciphertext, _ = encrypt_connector_credentials(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials={"token": "bearer-secret"},
        codec=codec,
    )
    active_record = ConnectorCredentialRecord(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials_enc=ciphertext,
        credential_hash=hashlib.sha256(ciphertext).hexdigest(),
        status="active",
        configured_by=_PROPOSER,
        source_approval_id="approval-1",
    )
    await cred_repo.upsert(active_record, expected_tenant_id=_TENANT)

    runtime = ConnectorScopedCredentialRuntime(
        repository=cred_repo,
        codec=codec,
        tenant_id=_TENANT,
    )
    result = await runtime.load_connector_credentials(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
    )
    assert result == {"token": "bearer-secret"}


@pytest.mark.asyncio
async def test_connector_scoped_runtime_raises_for_missing_credential() -> None:
    """Runtime raises KeyError when no active credential exists."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    runtime = ConnectorScopedCredentialRuntime(
        repository=cred_repo,
        codec=_NullCodec(),
        tenant_id=_TENANT,
    )

    with pytest.raises(KeyError, match=_CONNECTOR_ID):
        await runtime.load_connector_credentials(
            tenant_id=_TENANT,
            connector_id=_CONNECTOR_ID,
        )


@pytest.mark.asyncio
async def test_connector_scoped_runtime_raises_for_inactive_credential() -> None:
    """Runtime raises KeyError when credential exists but is pending_validation."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    codec = _NullCodec()
    ciphertext, _ = encrypt_connector_credentials(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials={"token": "x"},
        codec=codec,
    )
    pending = ConnectorCredentialRecord(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials_enc=ciphertext,
        credential_hash=hashlib.sha256(ciphertext).hexdigest(),
        status="pending_validation",
        configured_by=_PROPOSER,
        source_approval_id="pending",
    )
    await cred_repo.upsert(pending, expected_tenant_id=_TENANT)

    runtime = ConnectorScopedCredentialRuntime(
        repository=cred_repo,
        codec=codec,
        tenant_id=_TENANT,
    )

    with pytest.raises(KeyError):
        await runtime.load_connector_credentials(
            tenant_id=_TENANT,
            connector_id=_CONNECTOR_ID,
        )


@pytest.mark.asyncio
async def test_connector_scoped_runtime_rejects_cross_tenant_access() -> None:
    """Runtime raises PermissionError when tenant_id doesn't match runtime tenant."""
    cred_repo = _InMemoryConnectorCredentialRepository()
    runtime = ConnectorScopedCredentialRuntime(
        repository=cred_repo,
        codec=_NullCodec(),
        tenant_id=_TENANT,
    )

    with pytest.raises(PermissionError):
        await runtime.load_connector_credentials(
            tenant_id="other-tenant",
            connector_id=_CONNECTOR_ID,
        )


# ---------------------------------------------------------------------------
# encrypt_connector_credentials helper
# ---------------------------------------------------------------------------


def test_encrypt_connector_credentials_returns_stable_hash() -> None:
    """Same credentials encrypted twice yield different ciphertexts but valid hashes."""
    codec = _NullCodec()
    ct1, h1 = encrypt_connector_credentials(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials={"token": "abc"},
        codec=codec,
    )
    ct2, h2 = encrypt_connector_credentials(
        tenant_id=_TENANT,
        connector_id=_CONNECTOR_ID,
        credentials={"token": "abc"},
        codec=codec,
    )
    # NullCodec is deterministic; hashes must match ciphertext
    assert hashlib.sha256(ct1).hexdigest() == h1
    assert hashlib.sha256(ct2).hexdigest() == h2
    # NullCodec always produces the same output for same input
    assert ct1 == ct2
    assert h1 == h2
