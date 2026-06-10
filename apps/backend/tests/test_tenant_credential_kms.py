from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, cast

import pytest

from app.data_protection.crypto import MasterKeyRing
from app.tenant.credentials import (
    CredentialLifecycleState,
    GcpCloudKmsKeyProvider,
    LocalMasterKeyProvider,
    TenantCredentialEncryptor,
    TenantCredentialEnvelopeEncryptor,
    assert_credential_lifecycle_transition,
    channel_status_for_credential_lifecycle,
    credential_lifecycle_for_channel_status,
    is_opcred2,
)
from app.tenant.db.models import TenantChannelConfigurationRow
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.exceptions import TenantCredentialEncryptionError
from app.tenant.identity import derive_channel_configuration_id
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from scripts.reencrypt_tenant_credentials import (
    reencrypt_tenant_credential_rows,
)

_MASTER_KEY = "tenant-credential-kms-test-master-key-32-bytes"
_TENANT_ID = "tenant-kms"


@dataclass(frozen=True, slots=True)
class _KmsEncryptResponse:
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class _KmsDecryptResponse:
    plaintext: bytes


class _FakeGcpKmsClient:
    def __init__(self) -> None:
        self.encrypt_calls = 0
        self.decrypt_calls = 0
        self.fail_decrypt = False

    def encrypt(self, *, request: Mapping[str, object]) -> _KmsEncryptResponse:
        self.encrypt_calls += 1
        name = _request_text(request, "name")
        plaintext = _request_bytes(request, "plaintext")
        aad = _request_bytes(request, "additional_authenticated_data")
        payload = {
            "name": name,
            "aad": base64.b64encode(aad).decode("ascii"),
            "plaintext": base64.b64encode(plaintext).decode("ascii"),
        }
        return _KmsEncryptResponse(
            ciphertext=b"fake-gcp-kms:" + json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    def decrypt(self, *, request: Mapping[str, object]) -> _KmsDecryptResponse:
        self.decrypt_calls += 1
        if self.fail_decrypt:
            raise RuntimeError("kms unavailable")
        name = _request_text(request, "name")
        ciphertext = _request_bytes(request, "ciphertext")
        aad = _request_bytes(request, "additional_authenticated_data")
        if not ciphertext.startswith(b"fake-gcp-kms:"):
            raise RuntimeError("unknown ciphertext")
        payload = json.loads(ciphertext[len(b"fake-gcp-kms:") :].decode("utf-8"))
        if payload["name"] != name:
            raise RuntimeError("key resource mismatch")
        if base64.b64decode(payload["aad"]) != aad:
            raise RuntimeError("aad mismatch")
        return _KmsDecryptResponse(
            plaintext=base64.b64decode(payload["plaintext"])
        )


def test_local_provider_wrap_unwrap_round_trip() -> None:
    provider = _local_provider()
    dek = b"d" * 32

    wrapped = provider.wrap_dek(
        dek,
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
    )

    assert wrapped.provider == "local"
    assert wrapped.local_key_version == "v1"
    assert wrapped.wrapped_dek != dek
    assert provider.unwrap_dek(
        wrapped,
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
    ) == dek


@pytest.mark.parametrize(
    ("channel_type", "credentials"),
    [
        (
            TenantChannelType.WHATSAPP,
            {
                "access_token": "wa-token",
                "phone_number_id": "12345",
                "graph_api_version": "v25.0",
            },
        ),
        (
            TenantChannelType.EMAIL,
            {
                "access_key_id": "AKIA_TEST",
                "secret_access_key": "ses-secret",
                "region": "us-east-1",
            },
        ),
        (
            TenantChannelType.EMAIL,
            {
                "provider": "aws_ses_managed",
                "domain": "example.com",
                "region": "us-east-1",
                "identity_arn": "arn:aws:ses:us-east-1:123:identity/example.com",
                "dkim_tokens": ["token-a"],
                "mail_from_domain": "mail.example.com",
                "verification_status": "pending",
            },
        ),
        (
            TenantChannelType.EMAIL,
            {
                "provider": "aws_ses_byo",
                "role_arn": "arn:aws:iam::123:role/ses-send",
                "external_id": "external-id",
                "region": "us-east-1",
            },
        ),
        (TenantChannelType.SHOPIFY, {"access_token": "shpat_test"}),
    ],
)
def test_opcred2_encrypt_decrypt_round_trip_for_typed_schemas(
    channel_type: TenantChannelType,
    credentials: dict[str, Any],
) -> None:
    codec = _local_codec()

    encrypted = codec.encrypt(
        tenant_id=_TENANT_ID,
        channel_type=channel_type,
        credentials=credentials,
    )

    assert is_opcred2(encrypted)
    assert codec.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=channel_type,
        encrypted_credentials=encrypted,
    ) == credentials


def test_wrong_tenant_or_channel_aad_fails_decrypt() -> None:
    codec = _local_codec()
    encrypted = codec.encrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        credentials=_whatsapp_credentials(),
    )

    with pytest.raises(TenantCredentialEncryptionError):
        codec.decrypt(
            tenant_id="tenant-other",
            channel_type=TenantChannelType.WHATSAPP,
            encrypted_credentials=encrypted,
        )
    with pytest.raises(TenantCredentialEncryptionError):
        codec.decrypt(
            tenant_id=_TENANT_ID,
            channel_type=TenantChannelType.EMAIL,
            encrypted_credentials=encrypted,
        )


def test_legacy_opcred1_decrypt_still_works() -> None:
    legacy = TenantCredentialEncryptor(platform_master_key=_MASTER_KEY)
    codec = _local_codec()
    encrypted = legacy.encrypt(
        tenant_id=_TENANT_ID,
        credentials=_whatsapp_credentials(),
    )

    assert not is_opcred2(encrypted)
    assert codec.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        encrypted_credentials=encrypted,
    ) == _whatsapp_credentials()


def test_dual_read_supports_legacy_and_opcred2() -> None:
    legacy = TenantCredentialEncryptor(platform_master_key=_MASTER_KEY)
    codec = _local_codec()
    legacy_blob = legacy.encrypt(
        tenant_id=_TENANT_ID,
        credentials=_shopify_credentials(),
    )
    opcred2_blob = codec.encrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.SHOPIFY,
        credentials=_shopify_credentials(),
    )

    assert codec.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.SHOPIFY,
        encrypted_credentials=legacy_blob,
    ) == _shopify_credentials()
    assert codec.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.SHOPIFY,
        encrypted_credentials=opcred2_blob,
    ) == _shopify_credentials()


def test_reencrypt_migration_dry_run_changes_nothing() -> None:
    codec = _local_codec()
    row = _legacy_row()
    original_current = bytes(row.credentials_enc)
    original_previous = bytes(cast(bytes, row.previous_credentials_enc))

    summary = reencrypt_tenant_credential_rows(
        [row],
        credential_codec=codec,
        apply=False,
    )

    assert summary.dry_run is True
    assert summary.current_candidates == 1
    assert summary.previous_candidates == 1
    assert summary.current_migrated == 0
    assert summary.previous_migrated == 0
    assert row.credentials_enc == original_current
    assert row.previous_credentials_enc == original_previous


def test_reencrypt_migration_apply_migrates_current_and_previous() -> None:
    codec = _local_codec()
    row = _legacy_row()

    summary = reencrypt_tenant_credential_rows(
        [row],
        credential_codec=codec,
        apply=True,
    )

    assert summary.dry_run is False
    assert summary.current_candidates == 1
    assert summary.previous_candidates == 1
    assert summary.current_migrated == 1
    assert summary.previous_migrated == 1
    assert is_opcred2(bytes(row.credentials_enc))
    assert row.previous_credentials_enc is not None
    assert is_opcred2(bytes(row.previous_credentials_enc))
    assert codec.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.EMAIL,
        encrypted_credentials=bytes(row.credentials_enc),
    ) == _ses_credentials()


def test_reencrypt_migration_is_idempotent() -> None:
    codec = _local_codec()
    row = _legacy_row()
    reencrypt_tenant_credential_rows([row], credential_codec=codec, apply=True)
    first_current = bytes(row.credentials_enc)
    first_previous = bytes(cast(bytes, row.previous_credentials_enc))

    summary = reencrypt_tenant_credential_rows(
        [row],
        credential_codec=codec,
        apply=True,
    )

    assert summary.current_candidates == 0
    assert summary.previous_candidates == 0
    assert summary.current_migrated == 0
    assert summary.previous_migrated == 0
    assert row.credentials_enc == first_current
    assert row.previous_credentials_enc == first_previous


def test_dek_cache_avoids_second_gcp_unwrap_call() -> None:
    client = _FakeGcpKmsClient()
    provider = GcpCloudKmsKeyProvider(
        key_resource="projects/test/locations/global/keyRings/r/cryptoKeys/k",
        client=client,
    )
    codec = TenantCredentialEnvelopeEncryptor(
        default_provider=provider,
        providers={provider.backend: provider},
        legacy_encryptor=TenantCredentialEncryptor(platform_master_key=_MASTER_KEY),
        dek_cache_ttl_seconds=300,
    )
    encrypted = codec.encrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        credentials=_whatsapp_credentials(),
    )

    assert codec.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        encrypted_credentials=encrypted,
    ) == _whatsapp_credentials()
    assert codec.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        encrypted_credentials=encrypted,
    ) == _whatsapp_credentials()
    assert client.decrypt_calls == 1


def test_kms_cache_miss_failure_fails_closed() -> None:
    client = _FakeGcpKmsClient()
    provider = GcpCloudKmsKeyProvider(
        key_resource="projects/test/locations/global/keyRings/r/cryptoKeys/k",
        client=client,
    )
    codec = TenantCredentialEnvelopeEncryptor(
        default_provider=provider,
        providers={provider.backend: provider},
        legacy_encryptor=TenantCredentialEncryptor(platform_master_key=_MASTER_KEY),
        dek_cache_ttl_seconds=300,
    )
    encrypted = codec.encrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        credentials=_whatsapp_credentials(),
    )
    client.fail_decrypt = True

    with pytest.raises(TenantCredentialEncryptionError):
        codec.decrypt(
            tenant_id=_TENANT_ID,
            channel_type=TenantChannelType.WHATSAPP,
            encrypted_credentials=encrypted,
        )


def test_embedded_provider_metadata_controls_decrypt_not_default_backend() -> None:
    gcp_client = _FakeGcpKmsClient()
    gcp_provider = GcpCloudKmsKeyProvider(
        key_resource="projects/test/locations/global/keyRings/r/cryptoKeys/k",
        client=gcp_client,
    )
    gcp_writer = TenantCredentialEnvelopeEncryptor(
        default_provider=gcp_provider,
        providers={gcp_provider.backend: gcp_provider},
        legacy_encryptor=TenantCredentialEncryptor(platform_master_key=_MASTER_KEY),
    )
    encrypted = gcp_writer.encrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        credentials=_whatsapp_credentials(),
    )
    local_provider = _local_provider()
    local_default_reader = TenantCredentialEnvelopeEncryptor(
        default_provider=local_provider,
        providers={
            local_provider.backend: local_provider,
            gcp_provider.backend: gcp_provider,
        },
        legacy_encryptor=TenantCredentialEncryptor(platform_master_key=_MASTER_KEY),
    )

    assert local_default_reader.decrypt(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        encrypted_credentials=encrypted,
    ) == _whatsapp_credentials()
    assert gcp_client.decrypt_calls == 1


@pytest.mark.asyncio
async def test_current_whatsapp_send_path_aliases_still_load() -> None:
    runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=_local_codec(),
    )
    credentials = {
        "access_token": "wa-token",
        "phone_number_id": "12345",
        "graph_api_version": "v25.0",
    }

    record = await runtime.configure_channel(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
        routing_address="12345",
        credentials=credentials,
        webhook_secret="webhook-secret",
        status=TenantChannelStatus.ACTIVE,
    )

    assert is_opcred2(record.credentials_enc)
    assert await runtime.load_channel_credentials(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
    ) == credentials


@pytest.mark.asyncio
async def test_current_ses_send_path_aliases_still_load() -> None:
    runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=_local_codec(),
    )
    credentials = {
        "aws_access_key_id": "AKIA_TEST",
        "aws_secret_access_key": "ses-secret",
        "aws_region": "us-east-1",
        "aws_session_token": "session",
        "ses_endpoint_url": "https://email.test",
        "ses_configuration_set_name": "config-set",
    }

    record = await runtime.configure_channel(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        credentials=credentials,
        webhook_secret="arn:aws:sns:us-east-1:123:topic",
        status=TenantChannelStatus.ACTIVE,
    )

    assert is_opcred2(record.credentials_enc)
    assert await runtime.load_channel_credentials(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.EMAIL,
    ) == credentials


def test_malformed_credentials_rejected_before_encryption() -> None:
    codec = _local_codec()

    with pytest.raises(TenantCredentialEncryptionError):
        codec.encrypt(
            tenant_id=_TENANT_ID,
            channel_type=TenantChannelType.WHATSAPP,
            credentials={
                "phone_number_id": "12345",
                "graph_api_version": "v25.0",
            },
        )


def test_lifecycle_seam_maps_existing_statuses_and_enforces_transitions() -> None:
    assert (
        channel_status_for_credential_lifecycle(CredentialLifecycleState.PENDING)
        is TenantChannelStatus.PENDING_VALIDATION
    )
    assert (
        channel_status_for_credential_lifecycle(CredentialLifecycleState.VALIDATING)
        is TenantChannelStatus.PENDING_VALIDATION
    )
    assert (
        credential_lifecycle_for_channel_status(TenantChannelStatus.ERROR)
        is CredentialLifecycleState.FAILED
    )
    assert_credential_lifecycle_transition(
        current=CredentialLifecycleState.PENDING,
        target=CredentialLifecycleState.VALIDATING,
    )
    with pytest.raises(TenantCredentialEncryptionError):
        assert_credential_lifecycle_transition(
            current=CredentialLifecycleState.REVOKED,
            target=CredentialLifecycleState.ACTIVE,
        )


@pytest.mark.integration
def test_gcp_cloud_kms_provider_round_trip_when_env_configured() -> None:
    key_resource = (
        os.environ.get("OPERIOUS_KMS_KEY_RESOURCE", "").strip()
        or os.environ.get("GCP_KMS_KEY_RESOURCE", "").strip()
    )
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not key_resource or not credentials_path:
        pytest.skip(
            "OPERIOUS_KMS_KEY_RESOURCE/GCP_KMS_KEY_RESOURCE and "
            "GOOGLE_APPLICATION_CREDENTIALS are required for GCP KMS integration"
        )
    provider = GcpCloudKmsKeyProvider(key_resource=key_resource)
    dek = b"k" * 32

    wrapped = provider.wrap_dek(
        dek,
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
    )

    assert provider.unwrap_dek(
        wrapped,
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.WHATSAPP,
    ) == dek


def _local_provider() -> LocalMasterKeyProvider:
    return LocalMasterKeyProvider(
        master_key_ring=MasterKeyRing(
            keys={"v1": _MASTER_KEY},
            active_version="v1",
        )
    )


def _local_codec() -> TenantCredentialEnvelopeEncryptor:
    provider = _local_provider()
    return TenantCredentialEnvelopeEncryptor(
        default_provider=provider,
        providers={provider.backend: provider},
        legacy_encryptor=TenantCredentialEncryptor(platform_master_key=_MASTER_KEY),
        dek_cache_ttl_seconds=300,
    )


def _legacy_row() -> TenantChannelConfigurationRow:
    legacy = TenantCredentialEncryptor(platform_master_key=_MASTER_KEY)
    now = datetime.now(timezone.utc)
    return TenantChannelConfigurationRow(
        config_id=derive_channel_configuration_id(
            tenant_id=_TENANT_ID,
            channel_type=TenantChannelType.EMAIL,
        ),
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.EMAIL.value,
        status=TenantChannelStatus.ACTIVE.value,
        routing_address="support@example.com",
        credentials_enc=legacy.encrypt(
            tenant_id=_TENANT_ID,
            credentials=_ses_credentials(),
        ),
        webhook_secret="arn:aws:sns:us-east-1:123:topic",
        previous_credentials_enc=legacy.encrypt(
            tenant_id=_TENANT_ID,
            credentials={
                **_ses_credentials(),
                "access_key_id": "AKIA_PREVIOUS",
            },
        ),
        previous_webhook_secret="arn:aws:sns:us-east-1:123:previous",
        credential_rotated_at=now,
        credential_rotation_expires_at=now,
        verified_at=now,
        created_at=now,
        updated_at=now,
    )


def _whatsapp_credentials() -> dict[str, str]:
    return {
        "access_token": "wa-token",
        "phone_number_id": "12345",
        "graph_api_version": "v25.0",
    }


def _ses_credentials() -> dict[str, str]:
    return {
        "access_key_id": "AKIA_TEST",
        "secret_access_key": "ses-secret",
        "region": "us-east-1",
    }


def _shopify_credentials() -> dict[str, str]:
    return {"access_token": "shpat_test"}


def _request_text(request: Mapping[str, object], key: str) -> str:
    value = request[key]
    assert isinstance(value, str)
    return value


def _request_bytes(request: Mapping[str, object], key: str) -> bytes:
    value = request[key]
    assert isinstance(value, bytes)
    return value
