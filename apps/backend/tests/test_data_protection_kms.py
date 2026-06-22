"""GCP KMS custody for the data-protection master key (#54/#55).

The master key (KEK) is unwrapped from KMS-wrapped ciphertext at boot via the
real Cloud KMS client; it never sits at rest in plaintext when the backend is
GCP. These tests use a fake KMS client (test double — production wires the real
``google.cloud.kms_v1`` client) and exercise the real unwrap + ring-build logic.
"""

from __future__ import annotations

import base64
import os
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from app.core.config import Settings
from app.data_protection.crypto import DataProtectionError, MasterKeyRing
from app.data_protection.kms import (
    GcpKmsMasterKeyUnwrapper,
    build_master_key_unwrap,
)

_KEY_RESOURCE = (
    "projects/operious-kms/locations/global/keyRings/operious/"
    "cryptoKeys/data-protection"
)
_MASTER_AAD = b"operious:data_protection:master_key:v1"


class _FakeKmsClient:
    """Maps wrapped ciphertext -> plaintext; records request shape."""

    def __init__(self, mapping: Mapping[bytes, bytes]) -> None:
        self._mapping = dict(mapping)
        self.requests: list[Mapping[str, object]] = []

    def decrypt(self, *, request: Mapping[str, object]) -> Any:
        self.requests.append(request)
        ciphertext = request["ciphertext"]
        assert isinstance(ciphertext, bytes)
        if ciphertext not in self._mapping:
            raise RuntimeError("unknown ciphertext")
        return SimpleNamespace(plaintext=self._mapping[ciphertext])


class _RaisingKmsClient:
    def decrypt(self, *, request: Mapping[str, object]) -> Any:
        del request
        raise RuntimeError("kms unavailable")


def test_unwrapper_decrypts_with_correct_request_shape() -> None:
    kek = os.urandom(32)
    wrapped = b"wrapped-token-1"
    client = _FakeKmsClient({wrapped: kek})
    unwrapper = GcpKmsMasterKeyUnwrapper(key_resource=_KEY_RESOURCE, client=client)

    result = unwrapper.unwrap(wrapped)

    assert result == kek
    assert client.requests[0]["name"] == _KEY_RESOURCE
    assert client.requests[0]["ciphertext"] == wrapped
    assert client.requests[0]["additional_authenticated_data"] == _MASTER_AAD


def test_unwrapper_fails_closed_on_kms_error() -> None:
    unwrapper = GcpKmsMasterKeyUnwrapper(
        key_resource=_KEY_RESOURCE, client=_RaisingKmsClient()
    )
    with pytest.raises(DataProtectionError):
        unwrapper.unwrap(b"anything")


def test_unwrapper_requires_key_resource() -> None:
    with pytest.raises(DataProtectionError):
        GcpKmsMasterKeyUnwrapper(key_resource="   ", client=_FakeKmsClient({}))


def test_master_key_ring_uses_kms_unwrapped_kek() -> None:
    kek = os.urandom(32)
    wrapped = b"wrapped-token-ring"
    material = base64.b64encode(wrapped).decode("ascii")
    settings = Settings(
        ENVIRONMENT="test",
        DATA_PROTECTION_KMS_BACKEND="gcp",
        DATA_PROTECTION_MASTER_KEYS=f"v1:{material}",
        OPERIOUS_KMS_KEY_RESOURCE=_KEY_RESOURCE,
    )
    unwrapper = GcpKmsMasterKeyUnwrapper(
        key_resource=_KEY_RESOURCE, client=_FakeKmsClient({wrapped: kek})
    )

    ring = MasterKeyRing.from_settings(settings, master_key_unwrap=unwrapper.unwrap)

    # The ring's active KEK is the KMS-unwrapped plaintext, not the wrapped
    # material that sits at rest.
    assert ring._master(ring.active_version) == kek  # type: ignore[attr-defined]


def test_master_key_ring_rejects_non_base64_wrapped_material() -> None:
    settings = Settings(
        ENVIRONMENT="test",
        DATA_PROTECTION_KMS_BACKEND="gcp",
        DATA_PROTECTION_MASTER_KEYS="v1:!!! not base64 !!!",
        OPERIOUS_KMS_KEY_RESOURCE=_KEY_RESOURCE,
    )
    unwrapper = GcpKmsMasterKeyUnwrapper(
        key_resource=_KEY_RESOURCE, client=_FakeKmsClient({})
    )
    with pytest.raises(DataProtectionError):
        MasterKeyRing.from_settings(settings, master_key_unwrap=unwrapper.unwrap)


def test_build_master_key_unwrap_local_is_none() -> None:
    # Local backend wires no KMS client (plaintext key material).
    settings = Settings(ENVIRONMENT="test", DATA_PROTECTION_KMS_BACKEND="local")
    assert build_master_key_unwrap(settings) is None


# ─── Footgun guard: gcp backend + missing unwrap must fail loudly ─────────
#
# Three call sites (ticket_ingress_service.py, whatsapp_media_fetch_tasks.py,
# tenant/credentials.py) shipped without master_key_unwrap, which under the
# gcp backend silently used still-wrapped KMS ciphertext AS the AES key —
# wrong, valid-length, and undetectable until the first real decrypt threw
# InvalidTag. This guard turns that whole bug class into an immediate,
# unmissable construction-time error instead.


def test_master_key_ring_rejects_gcp_backend_with_no_unwrap() -> None:
    material = base64.b64encode(b"wrapped-token-footgun").decode("ascii")
    settings = Settings(
        ENVIRONMENT="test",
        DATA_PROTECTION_KMS_BACKEND="gcp",
        DATA_PROTECTION_MASTER_KEYS=f"v1:{material}",
        OPERIOUS_KMS_KEY_RESOURCE=_KEY_RESOURCE,
    )
    with pytest.raises(DataProtectionError, match="master_key_unwrap"):
        MasterKeyRing.from_settings(settings)  # master_key_unwrap omitted


def test_master_key_ring_local_backend_with_no_unwrap_is_unaffected() -> None:
    # The guard must not regress the legitimate local-backend path, where
    # master_key_unwrap=None is correct (plaintext key material at rest).
    settings = Settings(
        ENVIRONMENT="test",
        DATA_PROTECTION_KMS_BACKEND="local",
        DATA_PROTECTION_MASTER_KEYS="v1:" + base64.b64encode(os.urandom(32)).decode("ascii"),
    )
    ring = MasterKeyRing.from_settings(settings)
    assert ring.active_version == "v1"
