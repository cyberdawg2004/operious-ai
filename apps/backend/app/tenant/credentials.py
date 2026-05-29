"""Tenant credential encryption helpers.

Credential JSON is encrypted with AES-256-GCM. The AES key is derived
per tenant from the platform master key with HKDF-SHA256 using the
tenant id as salt. API read paths never call ``decrypt``; the runtime
method exists for boundary adapters that must perform outbound calls.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from typing import Any, Final, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.identity import coerce_tenant_id
from app.tenant.exceptions import TenantCredentialEncryptionError

_MAGIC: Final[bytes] = b"OPCRED1"
_NONCE_SIZE: Final[int] = 12
_KEY_SIZE: Final[int] = 32
_HKDF_INFO: Final[bytes] = b"operious.ai/tenant-credentials/aes-256-gcm/v1"


class TenantCredentialEncryptor:
    """Encrypt and decrypt tenant-owned credential JSON."""

    __slots__ = ("_master_key",)

    def __init__(self, *, platform_master_key: str | bytes) -> None:
        self._master_key = _decode_master_key(platform_master_key)

    def encrypt(
        self,
        *,
        tenant_id: str,
        credentials: Mapping[str, Any],
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


__all__ = ["TenantCredentialEncryptor"]
