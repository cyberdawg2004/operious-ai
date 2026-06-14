"""Recurrence guard for the 2026-06-11 master-key version-label collision.

On 2026-06-11 (commit 6955048) a dedicated KMS-custodied "v1" KEK was
introduced without bumping the version label, colliding with the
pre-existing implicit "v1" fallback (``TENANT_CREDENTIAL_MASTER_KEY``). 28
``data_protection_data_keys`` rows wrapped under the old material became
permanently undecryptable under the new ring.

This module covers:

* ``check_master_key_ring_compatibility`` — the readiness probe that would
  have caught the collision at deploy time (asserts NOT READY on a
  simulated repeat).
* ``MasterKeyRing.unwrap_key``'s "v1-legacy" fallback — it must rescue rows
  wrapped under the old material on ``InvalidTag`` of the primary key only,
  must never be reached by rows that already unwrap under the primary, and
  must still raise when no legacy candidate is registered.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_protection.crypto import (
    DataProtectionError,
    DataProtectionService,
    MasterKeyRing,
    check_master_key_ring_compatibility,
)
from app.data_protection.db.models import DataProtectionDataKeyRow
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

TENANT_ID = "tenant-master-key-recurrence-guard"

# Distinct 32-byte KEKs, expressed as hex (accepted by MasterKeyRing._decode_key).
_OLD_KEK = "11" * 32
_NEW_KEK = "22" * 32
_BOGUS_KEK = "33" * 32


@pytest.fixture
def pg_tenant_id() -> str:
    return TENANT_ID


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.tenants (tenant_id)
            VALUES (:tenant_id)
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": tenant_id},
    )
    await session.flush()


def _service(session: AsyncSession, ring: MasterKeyRing) -> DataProtectionService:
    return DataProtectionService(session, master_key_ring=ring)


@pytest.mark.asyncio
async def test_compatibility_check_passes_when_ring_matches_persisted_keys(
    pg_session: AsyncSession,
) -> None:
    await pg_session.execute(delete(DataProtectionDataKeyRow))
    await _ensure_tenant(pg_session, TENANT_ID)
    ring = MasterKeyRing(keys={"v1": _OLD_KEK}, active_version="v1")
    service = _service(pg_session, ring)
    await service.encrypt_text(
        "pre-collision secret",
        tenant_id=TENANT_ID,
        subject_id=None,
        field="x",
        tenant_scoped=True,
    )
    await pg_session.flush()

    assert await check_master_key_ring_compatibility(pg_session, ring) is True


@pytest.mark.asyncio
async def test_compatibility_check_fails_on_simulated_version_label_collision(
    pg_session: AsyncSession,
) -> None:
    """Reproduces the 06-11 incident: a "v1" label whose key material changed.

    Seeds a data key under ring-A's "v1" (the pre-06-11 KEK), then probes
    with ring-B, which reuses the "v1" label for *different* material (the
    06-11 dedicated KEK). The probe must report NOT READY (False) — exactly
    the signal that would have caught the collision before it shipped.
    """
    await pg_session.execute(delete(DataProtectionDataKeyRow))
    await _ensure_tenant(pg_session, TENANT_ID)
    ring_a = MasterKeyRing(keys={"v1": _OLD_KEK}, active_version="v1")
    service_a = _service(pg_session, ring_a)
    await service_a.encrypt_text(
        "pre-collision secret",
        tenant_id=TENANT_ID,
        subject_id=None,
        field="x",
        tenant_scoped=True,
    )
    await pg_session.flush()

    ring_b = MasterKeyRing(keys={"v1": _NEW_KEK}, active_version="v1")
    assert await check_master_key_ring_compatibility(pg_session, ring_b) is False


@pytest.mark.asyncio
async def test_legacy_fallback_rescues_pre_collision_row(
    pg_session: AsyncSession,
) -> None:
    """Approach A: a "v1-legacy" candidate rescues rows from the old ring."""
    await _ensure_tenant(pg_session, TENANT_ID)
    old_ring = MasterKeyRing(keys={"v1": _OLD_KEK}, active_version="v1")
    old_service = _service(pg_session, old_ring)
    ciphertext = await old_service.encrypt_text(
        "pre-collision secret",
        tenant_id=TENANT_ID,
        subject_id=None,
        field="x",
        tenant_scoped=True,
    )
    await pg_session.flush()

    new_ring = MasterKeyRing(
        keys={"v1": _NEW_KEK},
        active_version="v1",
        legacy_keys={"v1": _OLD_KEK},
    )
    rescued_service = _service(pg_session, new_ring)
    assert await rescued_service.decrypt_text(ciphertext) == "pre-collision secret"


@pytest.mark.asyncio
async def test_post_collision_row_never_reaches_legacy_candidate(
    pg_session: AsyncSession,
) -> None:
    """A row wrapped under the *current* primary must decrypt without the
    legacy candidate ever being consulted.

    The legacy candidate here is deliberately bogus key material: if the
    fallback were reached for this row, decryption would fail with
    ``DataProtectionError`` instead of returning the original plaintext.
    """
    await _ensure_tenant(pg_session, TENANT_ID)
    new_ring = MasterKeyRing(
        keys={"v1": _NEW_KEK},
        active_version="v1",
        legacy_keys={"v1": _BOGUS_KEK},
    )
    service = _service(pg_session, new_ring)
    ciphertext = await service.encrypt_text(
        "post-collision secret",
        tenant_id=TENANT_ID,
        subject_id=None,
        field="x",
        tenant_scoped=True,
    )
    await pg_session.flush()

    assert await service.decrypt_text(ciphertext) == "post-collision secret"


@pytest.mark.asyncio
async def test_unwrap_raises_when_primary_fails_and_no_legacy_candidate(
    pg_session: AsyncSession,
) -> None:
    """Without a registered legacy candidate, a stale "v1" row still raises."""
    await _ensure_tenant(pg_session, TENANT_ID)
    old_ring = MasterKeyRing(keys={"v1": _OLD_KEK}, active_version="v1")
    old_service = _service(pg_session, old_ring)
    ciphertext = await old_service.encrypt_text(
        "pre-collision secret",
        tenant_id=TENANT_ID,
        subject_id=None,
        field="x",
        tenant_scoped=True,
    )
    await pg_session.flush()

    new_ring = MasterKeyRing(keys={"v1": _NEW_KEK}, active_version="v1")
    new_service = _service(pg_session, new_ring)
    with pytest.raises(DataProtectionError):
        await new_service.decrypt_text(ciphertext)
