"""Break-control tests for OMS credential dual-control storage (PR 1).

Verifies:
  BC-1  Round-trip: encrypt → store (via propose→approve→apply) → decrypt →
        plaintext matches; wrong tenant_id raises.
  BC-2  Redaction: proposed_payload contains only sentinel keys; no credential
        fields appear anywhere in an API-layer change-request response.
  BC-3  No-plaintext-at-rest: during the pending-approval window the
        tenant_config_change_requests table holds only the hash sentinel, and
        tenant_channel_configurations.credentials_enc holds OPCRED2 ciphertext.
  BC-4  Dual-control: approver-equals-proposer is rejected.
  BC-5  Shape validation: bad auth_type / missing required fields / unknown
        fields are rejected before any write.
  BC-6  Rotation guard: proposing when an ACTIVE OMS credential already exists
        is rejected (rotation not yet supported in PR 1).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.tenant import TenantConfigChangeRequestResponse
from app.core.config import get_settings
from app.data_protection.crypto import MasterKeyRing
from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.services.tenant_configuration_service import TenantConfigurationService
from app.tenant.change_requests import (
    PostgresTenantConfigChangeRequestRepository,
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestSeparationError,
    TenantConfigChangeType,
)
from app.tenant.credentials import (
    LocalMasterKeyProvider,
    TenantCredentialEnvelopeEncryptor,
    TenantCredentialEncryptionError,
)
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_ALICE = "alice@example.com"
_BOB = "bob@example.com"

_BEARER_CREDS: dict[str, Any] = {"auth_type": "bearer", "token": "tok_abc123"}
_API_KEY_CREDS: dict[str, Any] = {"auth_type": "api_key", "api_key": "ak_xyz789"}
_BASIC_CREDS: dict[str, Any] = {
    "auth_type": "basic",
    "username": "user@oms.example.com",
    "password": "s3cr3t!",
}


class _RedisStub:
    async def publish(self, _channel: str, _payload: str) -> None:
        return None


def _encryptor(settings: Any) -> TenantCredentialEnvelopeEncryptor:
    ring = MasterKeyRing.from_settings(settings)
    provider = LocalMasterKeyProvider(master_key_ring=ring)
    return TenantCredentialEnvelopeEncryptor(default_provider=provider)


def _service(
    session: AsyncSession,
    encryptor: TenantCredentialEnvelopeEncryptor,
) -> TenantConfigChangeRequestService:
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=encryptor,
    )
    tenant_configuration = TenantConfigurationService(
        runtime=runtime,
        session=session,
        redis_client=_RedisStub(),
    )
    return TenantConfigChangeRequestService(
        repository=PostgresTenantConfigChangeRequestRepository(session),
        tenant_configuration_service=tenant_configuration,
        event_appender=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
        session=session,
    )


def _tenant() -> str:
    return f"tenant-oms-{uuid.uuid4().hex[:12]}"


async def _seed_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text(
            "INSERT INTO tenants (tenant_id, status) VALUES (:t, 'active') "
            "ON CONFLICT DO NOTHING"
        ),
        {"t": tenant_id},
    )


# ---------------------------------------------------------------------------
# BC-1  Round-trip: propose → approve → apply → decrypt matches plaintext
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bc1_round_trip_bearer(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_BEARER_CREDS,
        proposed_by=_ALICE,
    )
    assert proposal.change_type is TenantConfigChangeType.CREDENTIAL_UPDATE

    approved = await svc.approve(
        change_request_id=proposal.change_request_id,
        approved_by=_BOB,
        expected_tenant_id=tenant_id,
    )
    applied = await svc.apply(
        change_request_id=approved.change_request_id,
        expected_tenant_id=tenant_id,
        applied_by=_BOB,
    )
    assert applied.outcome_payload is not None
    assert applied.outcome_payload["channel"] == TenantChannelType.OMS.value
    assert applied.outcome_payload["status"] == TenantChannelStatus.ACTIVE.value

    # Decrypt and assert plaintext matches original
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=enc,
    )
    decrypted = await runtime.load_channel_credentials(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.OMS,
    )
    assert decrypted == _BEARER_CREDS


@pytest.mark.asyncio
async def test_bc1_round_trip_api_key(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_API_KEY_CREDS,
        proposed_by=_ALICE,
    )
    await svc.approve(
        change_request_id=proposal.change_request_id,
        approved_by=_BOB,
        expected_tenant_id=tenant_id,
    )
    await svc.apply(
        change_request_id=proposal.change_request_id,
        expected_tenant_id=tenant_id,
        applied_by=_BOB,
    )

    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=enc,
    )
    decrypted = await runtime.load_channel_credentials(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.OMS,
    )
    assert decrypted == _API_KEY_CREDS


@pytest.mark.asyncio
async def test_bc1_wrong_tenant_id_raises(pg_session: AsyncSession) -> None:
    """AAD binding: decrypting with the wrong tenant_id must fail."""
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_a = _tenant()
    tenant_b = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_a)
    await _seed_tenant(pg_session, tenant_a)
    await _seed_tenant(pg_session, tenant_b)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_a,
        credentials=_BEARER_CREDS,
        proposed_by=_ALICE,
    )
    await svc.approve(
        change_request_id=proposal.change_request_id,
        approved_by=_BOB,
        expected_tenant_id=tenant_a,
    )
    await svc.apply(
        change_request_id=proposal.change_request_id,
        expected_tenant_id=tenant_a,
        applied_by=_BOB,
    )

    # Fetch the raw ciphertext that belongs to tenant_a
    row = await pg_session.execute(
        text(
            "SELECT credentials_enc FROM tenant_channel_configurations "
            "WHERE tenant_id = :t AND channel_type = 'oms'"
        ),
        {"t": tenant_a},
    )
    ciphertext = bytes(row.scalar_one())

    # Attempt to decrypt it as tenant_b — AAD mismatch must raise
    with pytest.raises(TenantCredentialEncryptionError):
        enc.decrypt(
            tenant_id=tenant_b,
            encrypted_credentials=ciphertext,
            channel_type=TenantChannelType.OMS,
        )


# ---------------------------------------------------------------------------
# BC-2  Redaction: proposed_payload and API response contain no credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bc2_proposed_payload_sentinel_only(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_BEARER_CREDS,
        proposed_by=_ALICE,
    )

    payload = dict(proposal.proposed_payload)
    assert set(payload.keys()) == {"channel", "credential_hash", "_schema_version"}
    assert payload["channel"] == TenantChannelType.OMS.value
    assert len(payload["credential_hash"]) == 64  # SHA-256 hex
    # None of the credential keys appear
    for forbidden in ("token", "api_key", "password", "username", "auth_type"):
        assert forbidden not in payload


@pytest.mark.asyncio
async def test_bc2_api_response_no_credential_fields(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_BASIC_CREDS,
        proposed_by=_ALICE,
    )

    # Simulate the API schema serialisation + redaction layer
    response = TenantConfigChangeRequestResponse.from_record(proposal)
    payload_json = json.dumps(response.proposed_payload)

    for forbidden in ("password", "username", "auth_type", "token", "api_key"):
        assert forbidden not in payload_json


# ---------------------------------------------------------------------------
# BC-3  No-plaintext-at-rest: raw DB queries during the pending window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bc3_no_plaintext_at_rest_pending_window(
    pg_session: AsyncSession,
) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_BEARER_CREDS,
        proposed_by=_ALICE,
    )

    # --- Query 1: change-request table during pending window ---
    cr_row = await pg_session.execute(
        text(
            "SELECT proposed_payload FROM tenant_config_change_requests "
            "WHERE change_request_id = :crid"
        ),
        {"crid": str(proposal.change_request_id)},
    )
    raw_payload: dict = cr_row.scalar_one()
    payload_str = json.dumps(raw_payload)
    # Only sentinel keys should be present — no credential values
    for secret in ("tok_abc123", "bearer", "auth_type"):
        assert secret not in payload_str, (
            f"Credential data {secret!r} found in change_request payload "
            f"during pending window"
        )

    # --- Query 2: channel configurations table during pending window ---
    ch_row = await pg_session.execute(
        text(
            "SELECT credentials_enc, status FROM tenant_channel_configurations "
            "WHERE tenant_id = :t AND channel_type = 'oms'"
        ),
        {"t": tenant_id},
    )
    ch_result = ch_row.one()
    ciphertext = bytes(ch_result.credentials_enc)
    status = ch_result.status

    assert status == TenantChannelStatus.PENDING_VALIDATION.value
    # Must be an OPCRED2 envelope — starts with magic bytes
    assert ciphertext.startswith(b"OPCRED2:"), (
        "credentials_enc is not an OPCRED2 envelope during pending window"
    )
    # No plaintext credential values anywhere in the binary blob
    for secret in (b"tok_abc123", b"bearer"):
        assert secret not in ciphertext, (
            f"Plaintext {secret!r} found in credentials_enc ciphertext"
        )


# ---------------------------------------------------------------------------
# BC-4  Dual-control: approver must differ from proposer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bc4_self_approval_rejected(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_BEARER_CREDS,
        proposed_by=_ALICE,
    )

    with pytest.raises(TenantConfigChangeRequestSeparationError):
        await svc.approve(
            change_request_id=proposal.change_request_id,
            approved_by=_ALICE,  # same as proposer — must fail
            expected_tenant_id=tenant_id,
        )


@pytest.mark.asyncio
async def test_bc4_different_approver_succeeds(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_API_KEY_CREDS,
        proposed_by=_ALICE,
    )
    approved = await svc.approve(
        change_request_id=proposal.change_request_id,
        approved_by=_BOB,
        expected_tenant_id=tenant_id,
    )
    assert approved.approved_by == _BOB
    assert approved.proposed_by == _ALICE


# ---------------------------------------------------------------------------
# BC-5  Shape validation: bad credentials rejected before any write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bc5_unknown_auth_type_rejected(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    with pytest.raises(TenantCredentialEncryptionError, match="auth_type"):
        await svc.propose_oms_credential_update(
            tenant_id=tenant_id,
            credentials={"auth_type": "oauth2", "token": "tok"},
            proposed_by=_ALICE,
        )


@pytest.mark.asyncio
async def test_bc5_missing_token_for_bearer_rejected(
    pg_session: AsyncSession,
) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    with pytest.raises(TenantCredentialEncryptionError, match="token"):
        await svc.propose_oms_credential_update(
            tenant_id=tenant_id,
            credentials={"auth_type": "bearer"},  # missing token
            proposed_by=_ALICE,
        )


@pytest.mark.asyncio
async def test_bc5_unknown_field_rejected(pg_session: AsyncSession) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    with pytest.raises(TenantCredentialEncryptionError, match="unknown field"):
        await svc.propose_oms_credential_update(
            tenant_id=tenant_id,
            credentials={
                "auth_type": "bearer",
                "token": "tok_abc",
                "extra_field": "injected",  # must be rejected
            },
            proposed_by=_ALICE,
        )


# ---------------------------------------------------------------------------
# BC-6  Rotation guard: existing ACTIVE OMS credential blocks second propose
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bc6_rotation_guard_active_credential(
    pg_session: AsyncSession,
) -> None:
    settings = get_settings()
    enc = _encryptor(settings)
    svc = _service(pg_session, enc)
    tenant_id = _tenant()

    await set_pg_rls_tenant(pg_session, tenant_id)
    await _seed_tenant(pg_session, tenant_id)

    # First proposal: full cycle to ACTIVE
    proposal = await svc.propose_oms_credential_update(
        tenant_id=tenant_id,
        credentials=_BEARER_CREDS,
        proposed_by=_ALICE,
    )
    await svc.approve(
        change_request_id=proposal.change_request_id,
        approved_by=_BOB,
        expected_tenant_id=tenant_id,
    )
    await svc.apply(
        change_request_id=proposal.change_request_id,
        expected_tenant_id=tenant_id,
        applied_by=_BOB,
    )

    # Second proposal while credential is ACTIVE must be rejected
    with pytest.raises(
        TenantConfigChangeRequestLifecycleError,
        match="rotation",
    ):
        await svc.propose_oms_credential_update(
            tenant_id=tenant_id,
            credentials=_API_KEY_CREDS,
            proposed_by=_ALICE,
        )
