"""GCP Cloud KMS custody for the data-protection master key (#54/#55).

The data-protection master key (the KEK that wraps per-row data keys) must not
sit at rest in plaintext for enterprise/compliance posture. When
``DATA_PROTECTION_KMS_BACKEND=gcp``, ``DATA_PROTECTION_MASTER_KEYS`` entries hold
base64 GCP-KMS-wrapped ciphertext that this module unwraps via Cloud KMS at boot
to recover the plaintext KEK in memory only.

This uses the real ``google.cloud.kms_v1`` client (the same SDK the tenant
credential KMS path uses) — never a stub. Unwrap failures are fail-closed: the
service refuses to boot rather than fall back to plaintext.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any, Protocol, cast

from app.data_protection.crypto import DataProtectionError, MasterKeyUnwrap

# Platform-level AAD binding the wrapped master key to its purpose. The operator
# MUST wrap the plaintext KEK with this exact AAD, e.g.:
#   gcloud kms encrypt --key <KEY> --plaintext-file kek.bin \
#     --ciphertext-file kek.enc \
#     --additional-authenticated-data-file <(printf '%s' \
#       'operious:data_protection:master_key:v1')
_MASTER_KEY_AAD = b"operious:data_protection:master_key:v1"


class GcpKmsClientProtocol(Protocol):
    """Boundary for the external Google Cloud KMS client."""

    def decrypt(self, *, request: Mapping[str, object]) -> Any: ...


def build_gcp_kms_client() -> GcpKmsClientProtocol:
    """Construct the real Google Cloud KMS client (fail-closed if absent)."""

    try:
        kms_v1 = importlib.import_module("google.cloud.kms_v1")
        return cast(GcpKmsClientProtocol, kms_v1.KeyManagementServiceClient())
    except Exception as exc:  # noqa: BLE001
        raise DataProtectionError(
            "google-cloud-kms is required for DATA_PROTECTION_KMS_BACKEND=gcp"
        ) from exc


class GcpKmsMasterKeyUnwrapper:
    """Unwrap base64 KMS-wrapped data-protection master key material."""

    __slots__ = ("_client", "_key_resource")

    def __init__(
        self,
        *,
        key_resource: str,
        client: GcpKmsClientProtocol | None = None,
    ) -> None:
        resource = key_resource.strip()
        if not resource:
            raise DataProtectionError(
                "OPERIOUS_KMS_KEY_RESOURCE must be configured for "
                "DATA_PROTECTION_KMS_BACKEND=gcp"
            )
        self._key_resource = resource
        self._client = client or build_gcp_kms_client()

    @property
    def key_resource(self) -> str:
        return self._key_resource

    def unwrap(self, wrapped: bytes) -> bytes:
        """Return the plaintext KEK for one KMS-wrapped master key entry."""

        if not wrapped:
            raise DataProtectionError("wrapped master key material is empty")
        try:
            response = self._client.decrypt(
                request={
                    "name": self._key_resource,
                    "ciphertext": wrapped,
                    "additional_authenticated_data": _MASTER_KEY_AAD,
                }
            )
            plaintext = getattr(response, "plaintext")
        except Exception as exc:  # noqa: BLE001 - fail closed, never fall back.
            raise DataProtectionError(
                "data-protection master key could not be unwrapped by GCP "
                "Cloud KMS"
            ) from exc
        if not isinstance(plaintext, bytes) or not plaintext:
            raise DataProtectionError(
                "GCP Cloud KMS decrypt response did not include plaintext"
            )
        return bytes(plaintext)


def build_master_key_unwrap(settings: Any) -> MasterKeyUnwrap | None:
    """Return a KMS unwrap callable when the data-protection backend is GCP.

    ``None`` for the local backend (plaintext key material). Built by the DI
    composition root and passed into ``DataProtectionService.from_settings``.
    """
    backend = (
        str(getattr(settings, "DATA_PROTECTION_KMS_BACKEND", "local") or "local")
        .strip()
        .casefold()
    )
    if backend != "gcp":
        return None
    unwrapper = GcpKmsMasterKeyUnwrapper(
        key_resource=settings.data_protection_kms_key_resource,
    )
    return unwrapper.unwrap


__all__ = [
    "GcpKmsClientProtocol",
    "GcpKmsMasterKeyUnwrapper",
    "build_gcp_kms_client",
    "build_master_key_unwrap",
]
