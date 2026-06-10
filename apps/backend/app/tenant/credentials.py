"""Tenant credential encryption helpers.

``TenantCredentialEncryptor`` is the legacy OPCRED1 envelope retained for
dual-read migration. ``TenantCredentialEnvelopeEncryptor`` writes the OPCRED2
envelope: credential JSON is encrypted by a random DEK, and that DEK is wrapped
by a pluggable key provider whose structured metadata is embedded in the blob.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, cast, runtime_checkable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.data_protection.crypto import DataProtectionError, MasterKeyRing
from app.data_protection.db.models import DataProtectionDataKeyRow
from app.identity import coerce_tenant_id
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.exceptions import TenantCredentialEncryptionError

_MAGIC: Final[bytes] = b"OPCRED1"
_ENVELOPE_MAGIC: Final[bytes] = b"OPCRED2:"
_NONCE_SIZE: Final[int] = 12
_KEY_SIZE: Final[int] = 32
_HKDF_INFO: Final[bytes] = b"operious.ai/tenant-credentials/aes-256-gcm/v1"
_LOCAL_PROVIDER: Final[str] = "local"
_GCP_PROVIDER: Final[str] = "gcp"
_LOCAL_SCOPE: Final[str] = "tenant"
_DEFAULT_DEK_CACHE_TTL_SECONDS: Final[int] = 300
_MIN_DEK_CACHE_TTL_SECONDS: Final[int] = 0


def _empty_provider_metadata() -> dict[str, str]:
    return {}


class CredentialLifecycleState(StrEnum):
    """Credential lifecycle vocabulary mapped onto existing channel status."""

    PENDING = "pending"
    VALIDATING = "validating"
    ACTIVE = "active"
    FAILED = "failed"
    REVOKED = "revoked"


_LIFECYCLE_TO_CHANNEL_STATUS: Final[
    Mapping[CredentialLifecycleState, TenantChannelStatus]
] = {
    CredentialLifecycleState.PENDING: TenantChannelStatus.PENDING_VALIDATION,
    CredentialLifecycleState.VALIDATING: TenantChannelStatus.PENDING_VALIDATION,
    CredentialLifecycleState.ACTIVE: TenantChannelStatus.ACTIVE,
    CredentialLifecycleState.FAILED: TenantChannelStatus.VALIDATION_FAILED,
    CredentialLifecycleState.REVOKED: TenantChannelStatus.DISABLED,
}
_CHANNEL_STATUS_TO_LIFECYCLE: Final[
    Mapping[TenantChannelStatus, CredentialLifecycleState]
] = {
    TenantChannelStatus.PENDING_VERIFICATION: CredentialLifecycleState.PENDING,
    TenantChannelStatus.PENDING_VALIDATION: CredentialLifecycleState.PENDING,
    TenantChannelStatus.DRAFT: CredentialLifecycleState.PENDING,
    TenantChannelStatus.ACTIVE: CredentialLifecycleState.ACTIVE,
    TenantChannelStatus.ERROR: CredentialLifecycleState.FAILED,
    TenantChannelStatus.VALIDATION_FAILED: CredentialLifecycleState.FAILED,
    TenantChannelStatus.PAUSED: CredentialLifecycleState.REVOKED,
    TenantChannelStatus.DISABLED: CredentialLifecycleState.REVOKED,
}
_LIFECYCLE_TRANSITIONS: Final[
    Mapping[CredentialLifecycleState, frozenset[CredentialLifecycleState]]
] = {
    CredentialLifecycleState.PENDING: frozenset(
        {CredentialLifecycleState.VALIDATING, CredentialLifecycleState.REVOKED}
    ),
    CredentialLifecycleState.VALIDATING: frozenset(
        {
            CredentialLifecycleState.ACTIVE,
            CredentialLifecycleState.FAILED,
            CredentialLifecycleState.REVOKED,
        }
    ),
    CredentialLifecycleState.ACTIVE: frozenset(
        {CredentialLifecycleState.FAILED, CredentialLifecycleState.REVOKED}
    ),
    CredentialLifecycleState.FAILED: frozenset(
        {CredentialLifecycleState.VALIDATING, CredentialLifecycleState.REVOKED}
    ),
    CredentialLifecycleState.REVOKED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class WrappedDekMetadata:
    """Structured provider metadata stored inside an OPCRED2 envelope."""

    provider: str
    wrapped_dek: bytes
    key_resource: str | None = None
    local_key_version: str | None = None
    provider_metadata: Mapping[str, str] = field(
        default_factory=_empty_provider_metadata
    )


@runtime_checkable
class CredentialKeyProvider(Protocol):
    """Wrap and unwrap tenant credential DEKs."""

    @property
    def backend(self) -> str: ...

    def wrap_dek(
        self,
        plaintext_dek: bytes,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | str,
    ) -> WrappedDekMetadata: ...

    def unwrap_dek(
        self,
        wrapped_dek: WrappedDekMetadata,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | str,
    ) -> bytes: ...


class TenantCredentialCodec(Protocol):
    """Runtime credential encryption/decryption contract."""

    def encrypt(
        self,
        *,
        tenant_id: str,
        credentials: Mapping[str, Any],
        channel_type: TenantChannelType | str | None = None,
    ) -> bytes: ...

    def decrypt(
        self,
        *,
        tenant_id: str,
        encrypted_credentials: bytes,
        channel_type: TenantChannelType | str | None = None,
    ) -> dict[str, Any]: ...


class TenantCredentialEncryptor:
    """Encrypt and decrypt legacy OPCRED1 tenant-owned credential JSON."""

    __slots__ = ("_master_key",)

    def __init__(self, *, platform_master_key: str | bytes) -> None:
        self._master_key = _decode_master_key(platform_master_key)

    def encrypt(
        self,
        *,
        tenant_id: str,
        credentials: Mapping[str, Any],
        channel_type: TenantChannelType | str | None = None,
    ) -> bytes:
        tenant = str(coerce_tenant_id(tenant_id))
        nonce = os.urandom(_NONCE_SIZE)
        payload = _credential_json(credentials)
        ciphertext = AESGCM(self._derive_key(tenant)).encrypt(
            nonce,
            payload,
            _aad(tenant),
        )
        return _MAGIC + nonce + ciphertext

    def decrypt(
        self,
        *,
        tenant_id: str,
        encrypted_credentials: bytes,
        channel_type: TenantChannelType | str | None = None,
    ) -> dict[str, Any]:
        tenant = str(coerce_tenant_id(tenant_id))
        if not encrypted_credentials.startswith(_MAGIC):
            raise TenantCredentialEncryptionError(
                "credential payload has an unsupported envelope"
            )
        body = encrypted_credentials[len(_MAGIC) :]
        if len(body) <= _NONCE_SIZE:
            raise TenantCredentialEncryptionError(
                "credential payload is truncated"
            )
        nonce = body[:_NONCE_SIZE]
        ciphertext = body[_NONCE_SIZE:]
        try:
            plaintext = AESGCM(self._derive_key(tenant)).decrypt(
                nonce,
                ciphertext,
                _aad(tenant),
            )
        except InvalidTag as exc:
            raise TenantCredentialEncryptionError(
                "credential payload could not be authenticated"
            ) from exc
        decoded = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise TenantCredentialEncryptionError(
                "credential payload must decode to a JSON object"
            )
        decoded_payload = cast(dict[object, object], decoded)
        return {str(key): value for key, value in decoded_payload.items()}

    def _derive_key(self, tenant_id: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=_KEY_SIZE,
            salt=tenant_id.encode("utf-8"),
            info=_HKDF_INFO,
        ).derive(self._master_key)


class LocalMasterKeyProvider:
    """Credential DEK provider backed by the existing local MasterKeyRing."""

    __slots__ = ("_ring",)

    def __init__(self, *, master_key_ring: MasterKeyRing) -> None:
        self._ring = master_key_ring

    @classmethod
    def from_settings(cls, settings: Any) -> "LocalMasterKeyProvider":
        try:
            return cls(master_key_ring=MasterKeyRing.from_settings(settings))
        except DataProtectionError as exc:
            raise TenantCredentialEncryptionError(
                "local credential KMS provider is not configured"
            ) from exc

    @property
    def backend(self) -> str:
        return _LOCAL_PROVIDER

    def wrap_dek(
        self,
        plaintext_dek: bytes,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | str,
    ) -> WrappedDekMetadata:
        _require_dek(plaintext_dek)
        tenant = str(coerce_tenant_id(tenant_id))
        channel = _channel_value(channel_type)
        data_key_id = uuid.uuid4()  # EPHEMERAL: local wrapped-DEK metadata id
        scope_id = _local_scope_id(channel)
        try:
            version, wrapped_dek = self._ring.wrap_key(
                data_key=plaintext_dek,
                tenant_id=tenant,
                scope=_LOCAL_SCOPE,
                scope_id=scope_id,
                data_key_id=data_key_id,
            )
        except DataProtectionError as exc:
            raise TenantCredentialEncryptionError(
                "credential DEK could not be wrapped by local master key"
            ) from exc
        return WrappedDekMetadata(
            provider=self.backend,
            wrapped_dek=wrapped_dek,
            local_key_version=version,
            provider_metadata={
                "data_key_id": str(data_key_id),
                "scope": _LOCAL_SCOPE,
                "scope_id": scope_id,
            },
        )

    def unwrap_dek(
        self,
        wrapped_dek: WrappedDekMetadata,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | str,
    ) -> bytes:
        if wrapped_dek.provider != self.backend:
            raise TenantCredentialEncryptionError(
                "credential DEK provider metadata does not match local provider"
            )
        tenant = str(coerce_tenant_id(tenant_id))
        channel = _channel_value(channel_type)
        metadata = dict(wrapped_dek.provider_metadata)
        local_key_version = _required_text(
            wrapped_dek.local_key_version,
            "local credential key version is missing",
        )
        scope = metadata.get("scope") or _LOCAL_SCOPE
        scope_id = metadata.get("scope_id") or _local_scope_id(channel)
        if scope != _LOCAL_SCOPE or scope_id != _local_scope_id(channel):
            raise TenantCredentialEncryptionError(
                "local credential DEK metadata does not match channel scope"
            )
        try:
            data_key_id = uuid.UUID(_required_text(
                metadata.get("data_key_id"),
                "local credential data key id is missing",
            ))
            row = DataProtectionDataKeyRow(
                data_key_id=data_key_id,
                tenant_id=tenant,
                scope=scope,
                scope_id=scope_id,
                master_key_version=local_key_version,
                encrypted_key=wrapped_dek.wrapped_dek,
            )
            dek = self._ring.unwrap_key(row)
        except (DataProtectionError, ValueError) as exc:
            raise TenantCredentialEncryptionError(
                "credential DEK could not be unwrapped by local master key"
            ) from exc
        _require_dek(dek)
        return dek


class GcpKmsClientProtocol(Protocol):
    """Boundary for the external Google Cloud KMS client."""

    def encrypt(self, *, request: Mapping[str, object]) -> Any: ...

    def decrypt(self, *, request: Mapping[str, object]) -> Any: ...


class GcpCloudKmsKeyProvider:
    """Credential DEK provider backed by Google Cloud KMS."""

    __slots__ = ("_client", "_key_resource")

    def __init__(
        self,
        *,
        key_resource: str,
        client: GcpKmsClientProtocol | None = None,
    ) -> None:
        resource = key_resource.strip()
        if not resource:
            raise TenantCredentialEncryptionError(
                "OPERIOUS_KMS_KEY_RESOURCE must be configured for GCP KMS"
            )
        self._key_resource = resource
        self._client = client or _build_google_kms_client()

    @property
    def backend(self) -> str:
        return _GCP_PROVIDER

    @property
    def key_resource(self) -> str:
        return self._key_resource

    def wrap_dek(
        self,
        plaintext_dek: bytes,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | str,
    ) -> WrappedDekMetadata:
        _require_dek(plaintext_dek)
        tenant = str(coerce_tenant_id(tenant_id))
        channel = _channel_value(channel_type)
        try:
            response = self._client.encrypt(
                request={
                    "name": self._key_resource,
                    "plaintext": plaintext_dek,
                    "additional_authenticated_data": _credential_aad(
                        tenant,
                        channel,
                    ),
                }
            )
            ciphertext = getattr(response, "ciphertext")
        except Exception as exc:  # noqa: BLE001
            raise TenantCredentialEncryptionError(
                "credential DEK could not be wrapped by GCP Cloud KMS"
            ) from exc
        if not isinstance(ciphertext, bytes):
            raise TenantCredentialEncryptionError(
                "GCP Cloud KMS encrypt response did not include ciphertext"
            )
        return WrappedDekMetadata(
            provider=self.backend,
            key_resource=self._key_resource,
            wrapped_dek=bytes(ciphertext),
            provider_metadata={"aad": "tenant_channel_v1"},
        )

    def unwrap_dek(
        self,
        wrapped_dek: WrappedDekMetadata,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | str,
    ) -> bytes:
        if wrapped_dek.provider != self.backend:
            raise TenantCredentialEncryptionError(
                "credential DEK provider metadata does not match GCP provider"
            )
        tenant = str(coerce_tenant_id(tenant_id))
        channel = _channel_value(channel_type)
        key_resource = _required_text(
            wrapped_dek.key_resource,
            "GCP credential key resource is missing",
        )
        try:
            response = self._client.decrypt(
                request={
                    "name": key_resource,
                    "ciphertext": wrapped_dek.wrapped_dek,
                    "additional_authenticated_data": _credential_aad(
                        tenant,
                        channel,
                    ),
                }
            )
            plaintext = getattr(response, "plaintext")
        except Exception as exc:  # noqa: BLE001
            raise TenantCredentialEncryptionError(
                "credential DEK could not be unwrapped by GCP Cloud KMS"
            ) from exc
        if not isinstance(plaintext, bytes):
            raise TenantCredentialEncryptionError(
                "GCP Cloud KMS decrypt response did not include plaintext"
            )
        _require_dek(plaintext)
        return bytes(plaintext)


class TenantCredentialEnvelopeEncryptor:
    """OPCRED2 envelope encryption with dual-read legacy support."""

    __slots__ = ("_cache", "_default_provider", "_legacy_encryptor", "_providers")

    def __init__(
        self,
        *,
        default_provider: CredentialKeyProvider,
        providers: Mapping[str, CredentialKeyProvider] | None = None,
        legacy_encryptor: TenantCredentialEncryptor | None = None,
        dek_cache_ttl_seconds: int = _DEFAULT_DEK_CACHE_TTL_SECONDS,
    ) -> None:
        provider_map = {
            _normalize_provider(default_provider.backend): default_provider,
            **{
                _normalize_provider(provider.backend): provider
                for provider in (providers or {}).values()
            },
        }
        self._default_provider = default_provider
        self._providers = provider_map
        self._legacy_encryptor = legacy_encryptor
        self._cache = _DekCache(ttl_seconds=dek_cache_ttl_seconds)

    def encrypt(
        self,
        *,
        tenant_id: str,
        credentials: Mapping[str, Any],
        channel_type: TenantChannelType | str | None = None,
    ) -> bytes:
        tenant = str(coerce_tenant_id(tenant_id))
        channel = _require_channel_type(channel_type)
        payload = validate_channel_credentials(channel, credentials)
        dek = os.urandom(_KEY_SIZE)
        wrapped = self._default_provider.wrap_dek(
            dek,
            tenant_id=tenant,
            channel_type=channel,
        )
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = AESGCM(dek).encrypt(
            nonce,
            _credential_json(payload),
            _credential_aad(tenant, channel),
        )
        container = {
            "provider": wrapped.provider,
            "key_resource": wrapped.key_resource,
            "local_key_version": wrapped.local_key_version,
            "provider_metadata": dict(wrapped.provider_metadata),
            "wrapped_dek": _b64e(wrapped.wrapped_dek),
            "nonce": _b64e(nonce),
            "ciphertext": _b64e(ciphertext),
        }
        return _ENVELOPE_MAGIC + _json_bytes(container)

    def decrypt(
        self,
        *,
        tenant_id: str,
        encrypted_credentials: bytes,
        channel_type: TenantChannelType | str | None = None,
    ) -> dict[str, Any]:
        tenant = str(coerce_tenant_id(tenant_id))
        if not encrypted_credentials.startswith(_ENVELOPE_MAGIC):
            legacy = self._legacy_encryptor
            if legacy is None:
                raise TenantCredentialEncryptionError(
                    "legacy credential decrypt is unavailable"
                )
            decoded = legacy.decrypt(
                tenant_id=tenant,
                encrypted_credentials=encrypted_credentials,
                channel_type=channel_type,
            )
            if channel_type is None:
                return decoded
            return validate_channel_credentials(_channel_value(channel_type), decoded)

        channel = _require_channel_type(channel_type)
        try:
            container_raw = json.loads(
                encrypted_credentials[len(_ENVELOPE_MAGIC) :].decode("utf-8")
            )
            if not isinstance(container_raw, dict):
                raise ValueError("container must be a JSON object")
            container = cast(dict[str, object], container_raw)
            metadata = WrappedDekMetadata(
                provider=str(container["provider"]),
                key_resource=_optional_container_text(
                    container.get("key_resource")
                ),
                local_key_version=_optional_container_text(
                    container.get("local_key_version")
                ),
                provider_metadata=_provider_metadata(
                    container.get("provider_metadata")
                ),
                wrapped_dek=_b64d(str(container["wrapped_dek"])),
            )
            nonce = _b64d(str(container["nonce"]))
            ciphertext = _b64d(str(container["ciphertext"]))
        except Exception as exc:
            raise TenantCredentialEncryptionError(
                "credential OPCRED2 envelope is invalid"
            ) from exc
        if len(nonce) != _NONCE_SIZE:
            raise TenantCredentialEncryptionError(
                "credential OPCRED2 nonce has invalid length"
            )
        dek = self._unwrap_dek_cached(
            metadata,
            tenant_id=tenant,
            channel_type=channel,
        )
        try:
            plaintext = AESGCM(dek).decrypt(
                nonce,
                ciphertext,
                _credential_aad(tenant, channel),
            )
        except InvalidTag as exc:
            raise TenantCredentialEncryptionError(
                "credential OPCRED2 payload could not be authenticated"
            ) from exc
        decoded = _decoded_credential_json(plaintext)
        return validate_channel_credentials(channel, decoded)

    def _unwrap_dek_cached(
        self,
        wrapped_dek: WrappedDekMetadata,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | str,
    ) -> bytes:
        cache_key = _dek_cache_key(wrapped_dek)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        provider_name = _normalize_provider(wrapped_dek.provider)
        provider = self._providers.get(provider_name)
        if provider is None:
            raise TenantCredentialEncryptionError(
                f"credential key provider {provider_name!r} is unavailable"
            )
        dek = provider.unwrap_dek(
            wrapped_dek,
            tenant_id=tenant_id,
            channel_type=channel_type,
        )
        _require_dek(dek)
        self._cache.set(cache_key, dek)
        return dek


class _DekCache:
    __slots__ = ("_entries", "_ttl_seconds")

    def __init__(self, *, ttl_seconds: int) -> None:
        self._ttl_seconds = max(_MIN_DEK_CACHE_TTL_SECONDS, ttl_seconds)
        self._entries: dict[str, tuple[float, bytes]] = {}

    def get(self, key: str) -> bytes | None:
        if self._ttl_seconds <= 0:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: bytes) -> None:
        if self._ttl_seconds <= 0:
            return
        self._entries[key] = (time.monotonic() + self._ttl_seconds, bytes(value))


class ChannelCredentialValidator(Protocol):
    """Format-validation seam for future live channel validators."""

    def validate_format(
        self,
        *,
        channel_type: TenantChannelType | str,
        credentials: Mapping[str, Any],
    ) -> dict[str, Any]: ...


class FormatChannelCredentialValidator:
    """Schema-shape validator used before encryption and after decrypt."""

    def validate_format(
        self,
        *,
        channel_type: TenantChannelType | str,
        credentials: Mapping[str, Any],
    ) -> dict[str, Any]:
        return validate_channel_credentials(channel_type, credentials)


def build_tenant_credential_encryptor_from_settings(
    settings: Any,
) -> TenantCredentialEnvelopeEncryptor:
    """Build the tenant credential codec from centralized settings."""

    backend = _normalize_provider(
        str(getattr(settings, "CREDENTIAL_KMS_BACKEND", _LOCAL_PROVIDER))
    )
    if backend not in {_LOCAL_PROVIDER, _GCP_PROVIDER}:
        raise TenantCredentialEncryptionError(
            "CREDENTIAL_KMS_BACKEND must be 'local' or 'gcp'"
        )

    providers: dict[str, CredentialKeyProvider] = {}
    local_provider = _maybe_local_provider(settings)
    if local_provider is not None:
        providers[local_provider.backend] = local_provider

    key_resource = kms_key_resource_from_settings(settings)
    if backend == _GCP_PROVIDER:
        gcp_provider = GcpCloudKmsKeyProvider(key_resource=key_resource)
        providers[gcp_provider.backend] = gcp_provider
    elif key_resource:
        try:
            gcp_provider = GcpCloudKmsKeyProvider(key_resource=key_resource)
        except TenantCredentialEncryptionError:
            gcp_provider = None
        if gcp_provider is not None:
            providers[gcp_provider.backend] = gcp_provider

    default_provider = providers.get(backend)
    if default_provider is None:
        raise TenantCredentialEncryptionError(
            f"credential KMS backend {backend!r} is not configured"
        )

    legacy_encryptor = _maybe_legacy_encryptor(settings)
    ttl = int(
        getattr(
            settings,
            "CREDENTIAL_DEK_CACHE_TTL_SECONDS",
            _DEFAULT_DEK_CACHE_TTL_SECONDS,
        )
    )
    return TenantCredentialEnvelopeEncryptor(
        default_provider=default_provider,
        providers=providers,
        legacy_encryptor=legacy_encryptor,
        dek_cache_ttl_seconds=ttl,
    )


def kms_key_resource_from_settings(settings: Any) -> str:
    """Return canonical KMS key resource, accepting the legacy alias."""

    canonical = str(getattr(settings, "OPERIOUS_KMS_KEY_RESOURCE", "") or "").strip()
    if canonical:
        return canonical
    return str(getattr(settings, "GCP_KMS_KEY_RESOURCE", "") or "").strip()


def is_opcred2(encrypted_credentials: bytes) -> bool:
    return encrypted_credentials.startswith(_ENVELOPE_MAGIC)


def validate_channel_credentials(
    channel_type: TenantChannelType | str,
    credentials: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate channel credential shape while preserving existing field names."""

    normalized = _credential_mapping(credentials)
    channel = _channel_value(channel_type)
    if channel == TenantChannelType.WHATSAPP.value:
        _validate_whatsapp_credentials(normalized)
    elif channel == TenantChannelType.EMAIL.value:
        _validate_ses_credentials(normalized)
    elif channel == TenantChannelType.SHOPIFY.value:
        _required_credential_text(normalized, ("access_token",), "shopify")
    _credential_json(normalized)
    return normalized


def channel_status_for_credential_lifecycle(
    state: CredentialLifecycleState | str,
) -> TenantChannelStatus:
    lifecycle = CredentialLifecycleState(str(state))
    return _LIFECYCLE_TO_CHANNEL_STATUS[lifecycle]


def credential_lifecycle_for_channel_status(
    status: TenantChannelStatus | str,
) -> CredentialLifecycleState:
    channel_status = TenantChannelStatus(str(status))
    return _CHANNEL_STATUS_TO_LIFECYCLE[channel_status]


def assert_credential_lifecycle_transition(
    *,
    current: CredentialLifecycleState | str,
    target: CredentialLifecycleState | str,
) -> None:
    current_state = CredentialLifecycleState(str(current))
    target_state = CredentialLifecycleState(str(target))
    if target_state not in _LIFECYCLE_TRANSITIONS[current_state]:
        raise TenantCredentialEncryptionError(
            f"illegal credential lifecycle transition "
            f"{current_state.value}->{target_state.value}"
        )


def _decode_master_key(raw: str | bytes) -> bytes:
    if isinstance(raw, bytes):
        key = raw
    else:
        text = raw.strip()
        if not text:
            raise TenantCredentialEncryptionError(
                "TENANT_CREDENTIAL_MASTER_KEY must be configured"
            )
        key = _try_decode_base64(text) or _try_decode_hex(text) or text.encode(
            "utf-8"
        )
    if len(key) < _KEY_SIZE:
        raise TenantCredentialEncryptionError(
            "TENANT_CREDENTIAL_MASTER_KEY must contain at least 32 bytes"
        )
    return key


def _try_decode_base64(text: str) -> bytes | None:
    try:
        decoded = base64.b64decode(text, validate=True)
    except Exception:
        return None
    return decoded if decoded else None


def _try_decode_hex(text: str) -> bytes | None:
    try:
        decoded = bytes.fromhex(text)
    except ValueError:
        return None
    return decoded if decoded else None


def _credential_json(credentials: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            credentials,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TenantCredentialEncryptionError(
            "credentials must be JSON serializable"
        ) from exc


def _aad(tenant_id: str) -> bytes:
    return f"tenant_id:{tenant_id}".encode("utf-8")


def _build_google_kms_client() -> GcpKmsClientProtocol:
    try:
        kms_v1 = importlib.import_module("google.cloud.kms_v1")
        return cast(GcpKmsClientProtocol, kms_v1.KeyManagementServiceClient())
    except Exception as exc:  # noqa: BLE001
        raise TenantCredentialEncryptionError(
            "google-cloud-kms is required for CREDENTIAL_KMS_BACKEND=gcp"
        ) from exc


def _maybe_local_provider(settings: Any) -> LocalMasterKeyProvider | None:
    if (
        not str(getattr(settings, "DATA_PROTECTION_MASTER_KEYS", "") or "").strip()
        and not str(getattr(settings, "TENANT_CREDENTIAL_MASTER_KEY", "") or "").strip()
    ):
        return None
    return LocalMasterKeyProvider.from_settings(settings)


def _maybe_legacy_encryptor(settings: Any) -> TenantCredentialEncryptor | None:
    master_key = str(getattr(settings, "TENANT_CREDENTIAL_MASTER_KEY", "") or "")
    if not master_key.strip():
        return None
    return TenantCredentialEncryptor(platform_master_key=master_key)


def _credential_mapping(credentials: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in credentials.items()}


def _validate_whatsapp_credentials(credentials: Mapping[str, Any]) -> None:
    provider = _optional_credential_text(credentials, ("provider",))
    if provider == "meta_whatsapp_embedded":
        _required_credential_text(credentials, ("waba_id",), "whatsapp")
        _required_credential_text(
            credentials,
            ("phone_number_id", "whatsapp_phone_number_id"),
            "whatsapp",
        )
        _required_credential_text(credentials, ("business_token",), "whatsapp")
        _required_credential_text(credentials, ("app_secret",), "whatsapp")
        _required_credential_text(
            credentials,
            ("verify_token", "webhook_verify_token"),
            "whatsapp",
        )
        return
    if provider == "meta_whatsapp_manual":
        _required_credential_text(
            credentials,
            ("access_token", "graph_api_access_token", "bearer_token"),
            "whatsapp",
        )
        _required_credential_text(
            credentials,
            ("phone_number_id", "whatsapp_phone_number_id"),
            "whatsapp",
        )
        _required_credential_text(credentials, ("graph_api_version",), "whatsapp")
        _required_credential_text(
            credentials,
            ("verify_token", "webhook_verify_token"),
            "whatsapp",
        )
        return
    _required_credential_text(
        credentials,
        ("access_token", "graph_api_access_token", "bearer_token"),
        "whatsapp",
    )
    _required_credential_text(
        credentials,
        ("phone_number_id", "whatsapp_phone_number_id"),
        "whatsapp",
    )
    _required_credential_text(credentials, ("graph_api_version",), "whatsapp")


def _validate_ses_credentials(credentials: Mapping[str, Any]) -> None:
    provider = _optional_credential_text(credentials, ("provider",))
    if provider == "aws_ses_managed":
        _required_credential_text(
            credentials,
            ("domain", "source_domain", "source_email_address"),
            "ses",
        )
        _required_credential_text(
            credentials,
            ("region", "aws_region", "ses_region"),
            "ses",
        )
        tokens = credentials.get("dkim_tokens")
        if tokens is not None and (
            not isinstance(tokens, list)
            or any(
                not isinstance(token, str) or not token.strip()
                for token in cast(list[object], tokens)
            )
        ):
            raise TenantCredentialEncryptionError(
                "tenant ses credential dkim_tokens must contain non-empty strings"
            )
        return
    if provider in {"aws_ses_byo", "aws_ses_byo_role"}:
        _required_credential_text(credentials, ("role_arn",), "ses")
        _required_credential_text(credentials, ("external_id",), "ses")
        _required_credential_text(
            credentials,
            ("region", "aws_region", "ses_region"),
            "ses",
        )
        return
    if provider == "aws_ses_byo_access_key":
        _required_credential_text(
            credentials,
            ("access_key_id", "aws_access_key_id"),
            "ses",
        )
        _required_credential_text(
            credentials,
            ("secret_access_key", "aws_secret_access_key"),
            "ses",
        )
        _required_credential_text(
            credentials,
            ("region", "aws_region", "ses_region"),
            "ses",
        )
        _required_credential_text(
            credentials,
            ("source_email_address", "from_email_address", "domain"),
            "ses",
        )
        return
    _required_credential_text(
        credentials,
        ("access_key_id", "aws_access_key_id"),
        "ses",
    )
    _required_credential_text(
        credentials,
        ("secret_access_key", "aws_secret_access_key"),
        "ses",
    )
    _required_credential_text(
        credentials,
        ("region", "aws_region", "ses_region"),
        "ses",
    )


def _required_credential_text(
    credentials: Mapping[str, Any],
    keys: tuple[str, ...],
    channel: str,
) -> str:
    value = _optional_credential_text(credentials, keys)
    if value is None:
        raise TenantCredentialEncryptionError(
            f"tenant {channel} credential {keys[0]} is required"
        )
    return value


def _optional_credential_text(
    credentials: Mapping[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = credentials.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _decoded_credential_json(plaintext: bytes) -> dict[str, Any]:
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise TenantCredentialEncryptionError(
            "credential payload must decode to a JSON object"
        )
    decoded_payload = cast(dict[object, object], decoded)
    return {str(key): value for key, value in decoded_payload.items()}


def _credential_aad(tenant_id: str, channel: str) -> bytes:
    return f"tenant_id:{tenant_id}|channel:{channel}|opcred2".encode("utf-8")


def _local_scope_id(channel: str) -> str:
    return f"tenant-credentials:{channel}"


def _require_dek(value: bytes) -> None:
    if len(value) != _KEY_SIZE:
        raise TenantCredentialEncryptionError("credential DEK must be 32 bytes")


def _required_text(value: str | None, message: str) -> str:
    text = (value or "").strip()
    if not text:
        raise TenantCredentialEncryptionError(message)
    return text


def _require_channel_type(channel_type: TenantChannelType | str | None) -> str:
    if channel_type is None:
        raise TenantCredentialEncryptionError(
            "channel_type is required for OPCRED2 credentials"
        )
    return _channel_value(channel_type)


def _channel_value(channel_type: TenantChannelType | str) -> str:
    if isinstance(channel_type, TenantChannelType):
        return channel_type.value
    channel = str(channel_type).strip()
    if not channel:
        raise TenantCredentialEncryptionError("credential channel_type is required")
    return channel


def _normalize_provider(provider: str) -> str:
    return provider.strip().casefold()


def _optional_container_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    raise TenantCredentialEncryptionError("credential OPCRED2 metadata is invalid")


def _provider_metadata(value: object) -> Mapping[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TenantCredentialEncryptionError("credential provider metadata is invalid")
    result: dict[str, str] = {}
    metadata = cast(dict[object, object], value)
    for key, item in metadata.items():
        if not isinstance(item, str):
            raise TenantCredentialEncryptionError(
                "credential provider metadata values must be strings"
            )
        result[str(key)] = item
    return result


def _dek_cache_key(wrapped_dek: WrappedDekMetadata) -> str:
    digest = hashlib.sha256()
    digest.update(_normalize_provider(wrapped_dek.provider).encode("utf-8"))
    digest.update(b"\0")
    digest.update((wrapped_dek.key_resource or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update((wrapped_dek.local_key_version or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(
        json.dumps(
            dict(wrapped_dek.provider_metadata),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\0")
    digest.update(wrapped_dek.wrapped_dek)
    return digest.hexdigest()


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "ChannelCredentialValidator",
    "CredentialKeyProvider",
    "CredentialLifecycleState",
    "FormatChannelCredentialValidator",
    "GcpCloudKmsKeyProvider",
    "GcpKmsClientProtocol",
    "LocalMasterKeyProvider",
    "TenantCredentialCodec",
    "TenantCredentialEncryptor",
    "TenantCredentialEnvelopeEncryptor",
    "WrappedDekMetadata",
    "assert_credential_lifecycle_transition",
    "build_tenant_credential_encryptor_from_settings",
    "channel_status_for_credential_lifecycle",
    "credential_lifecycle_for_channel_status",
    "is_opcred2",
    "kms_key_resource_from_settings",
    "validate_channel_credentials",
]
