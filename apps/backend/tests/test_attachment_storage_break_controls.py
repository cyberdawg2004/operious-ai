"""Break-control tests for PR-B1a — customer attachment storage foundation.

Verified properties:
  BC-1  migration 0088: tenant_attachments has relrowsecurity=True AND
        relforcerowsecurity=True, included in the generic RLS-coverage
        invariant sweep.
  BC-2  cross-tenant probe: tenant A context sees only A's rows, tenant B
        context sees only B's rows, no context sees zero rows (FORCE RLS),
        negative control: owner (BYPASSRLS) sees both.
  BC-3  encrypted-at-rest is APP-LAYER, not just SSE: the raw S3 object is
        ciphertext (not the plaintext, and the plaintext is not even a
        substring), and AttachmentRepository.get() decrypts it back to the
        exact original bytes.
  BC-4  magic-byte sniffing rejects a renamed executable BEFORE any S3
        write is attempted — proven with a blob store stub that raises if
        ever called, not just by asserting on the row afterward.
  BC-5  the streaming size cap aborts as soon as the cumulative size
        exceeds the limit, without ever draining an oversized source.
  BC-6  the attachment content-type allow-list is a SEPARATE set from the
        knowledge-upload allow-list (images admitted here, not there).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.attachments.exceptions import AttachmentNotFoundError
from app.attachments.records import AttachmentRecord
from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.attachments.sniffing import ATTACHMENT_ALLOWED_CONTENT_TYPES
from app.attachments.storage_service import AttachmentStorageService
from app.attachments.streaming import AttachmentTooLargeError, read_bounded
from app.core.config import Settings
from app.data_protection.crypto import DataProtectionService, MasterKeyRing
from app.tenant.file_ingestion import ALLOWED_CONTENT_TYPES as KNOWLEDGE_ALLOWED_TYPES
from tests.conftest import TEST_DATABASE_URL_ENV, requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_RESTRICTED_ROLE = "operious_app_test"
_ROLE_REQUIRED_ENV = "RLS_RESTRICTED_ROLE_REQUIRED"

requires_s3 = pytest.mark.skipif(
    not os.environ.get("ATTACHMENTS_S3_BUCKET"),
    reason=(
        "requires ATTACHMENTS_S3_BUCKET (+ region/credentials) pointed at "
        "a real S3 bucket — set the 4 ATTACHMENTS_S3_* env vars to enable "
        "the real-S3 break-controls."
    ),
)


# ─── shared helpers ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_conn() -> AsyncIterator[asyncpg.Connection]:
    dsn = os.environ[TEST_DATABASE_URL_ENV].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(dsn)
    try:
        yield conn
    finally:
        await conn.close()


async def _enter_restricted_role(session: AsyncSession) -> None:
    try:
        await session.execute(text(f"SET LOCAL ROLE {_RESTRICTED_ROLE}"))
    except SQLAlchemyError as exc:
        if os.environ.get(_ROLE_REQUIRED_ENV) == "1":
            raise AssertionError(
                f"restricted RLS role {_RESTRICTED_ROLE!r} is required in CI"
            ) from exc
        pytest.skip(f"restricted RLS role unavailable: {exc}")
    current_user = (await session.execute(text("SELECT current_user"))).scalar_one()
    assert current_user == _RESTRICTED_ROLE


async def _seed_rows(
    *,
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    statements: list[tuple[str, dict[str, Any]]],
) -> None:
    if pg_seed_engine is None:
        for statement, params in statements:
            await pg_session.execute(text(statement), params)
        await pg_session.flush()
        return
    async with pg_seed_engine.begin() as connection:
        for statement, params in statements:
            await connection.execute(text(statement), params)


def _dp_service(session: Any) -> DataProtectionService:
    return DataProtectionService(
        session,
        master_key_ring=MasterKeyRing(keys={"v1": b"a" * 32}, active_version="v1"),
    )


class _RefusingBlobStore:
    """Stub that fails the test if S3 is ever touched.

    Used to prove the magic-byte-reject path never reaches the network,
    not just that the resulting row happens to lack a storage_key.
    """

    def put(self, key: str, ciphertext: bytes) -> None:
        raise AssertionError("S3 put() must never be called for a rejected upload")

    def get(self, key: str) -> bytes:
        raise AssertionError("S3 get() must never be called for a rejected upload")

    def delete(self, key: str) -> None:
        raise AssertionError("S3 delete() must never be called for a rejected upload")


async def _ensure_tenant_row(
    *,
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    tenant_id: str,
) -> None:
    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=[
            (
                """
                INSERT INTO public.tenants (tenant_id, status)
                VALUES (:tenant_id, 'active')
                ON CONFLICT (tenant_id) DO NOTHING
                """,
                {"tenant_id": tenant_id},
            )
        ],
    )


# ─── BC-1: migration 0088 — RLS + FORCE RLS flags ─────────────────────────


@pytest.mark.asyncio
async def test_tenant_attachments_force_rls_flags(
    db_conn: asyncpg.Connection,
) -> None:
    row = await db_conn.fetchrow(
        """
        SELECT c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'tenant_attachments'
        """
    )
    assert row is not None, "tenant_attachments not found in pg_class"
    assert row["relrowsecurity"] is True, (
        "tenant_attachments: relrowsecurity=False — migration 0088 not applied"
    )
    assert row["relforcerowsecurity"] is True, (
        "tenant_attachments: relforcerowsecurity=False — table owner bypasses RLS"
    )
    policy = await db_conn.fetchrow(
        """
        SELECT policyname FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'tenant_attachments'
          AND policyname = 'tenant_isolation'
        """
    )
    assert policy is not None, "tenant_isolation policy missing on tenant_attachments"


@pytest.mark.asyncio
async def test_tenant_attachments_included_in_rls_coverage_invariant(
    db_conn: asyncpg.Connection,
) -> None:
    unprotected = await db_conn.fetch(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'tenant_attachments'
          AND NOT c.relrowsecurity
        """
    )
    assert not unprotected, "tenant_attachments is missing RLS — invariant would fail"

    not_forced = await db_conn.fetch(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'tenant_attachments'
          AND c.relrowsecurity
          AND NOT c.relforcerowsecurity
        """
    )
    assert not not_forced, (
        "tenant_attachments has RLS but not FORCED — "
        "test_every_tenant_table_forces_rls would fail"
    )


# ─── BC-2: cross-tenant restricted-role probe ─────────────────────────────


@pytest.mark.asyncio
async def test_restricted_role_filters_tenant_attachments(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_a = f"rls-att-a-{uuid.uuid4().hex}"
    tenant_b = f"rls-att-b-{uuid.uuid4().hex}"

    statements: list[tuple[str, dict[str, Any]]] = []
    for tenant_id in (tenant_a, tenant_b):
        statements.extend(
            [
                (
                    """
                    INSERT INTO public.tenants (tenant_id, status)
                    VALUES (:tenant_id, 'active')
                    ON CONFLICT (tenant_id) DO NOTHING
                    """,
                    {"tenant_id": tenant_id},
                ),
                (
                    """
                    INSERT INTO public.tenant_attachments (
                        attachment_id, tenant_id, channel, storage_backend,
                        storage_key, size_bytes, sha256_digest, status
                    ) VALUES (
                        :attachment_id, :tenant_id, 'email', 's3',
                        :storage_key, 10, 'deadbeef', 'stored'
                    )
                    """,
                    {
                        "attachment_id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "storage_key": f"{tenant_id}/probe",
                    },
                ),
            ]
        )

    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=statements,
    )

    # Negative control: owner (BYPASSRLS=true) sees both tenants' rows.
    owner_count = int(
        (
            await pg_session.execute(
                text(
                    "SELECT count(*) FROM public.tenant_attachments"
                    " WHERE tenant_id = :a OR tenant_id = :b"
                ),
                {"a": tenant_a, "b": tenant_b},
            )
        ).scalar_one()
    )
    assert owner_count == 2, (
        f"owner should see rows for both tenants (got {owner_count}); "
        "negative control failed — BYPASSRLS may not be set on the db role"
    )

    await _enter_restricted_role(pg_session)

    await set_pg_rls_tenant(pg_session, tenant_a)
    count_a = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.tenant_attachments")
            )
        ).scalar_one()
    )
    assert count_a == 1, (
        f"restricted role + tenant A context: expected 1 row, got {count_a}"
    )

    await set_pg_rls_tenant(pg_session, tenant_b)
    count_b = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.tenant_attachments")
            )
        ).scalar_one()
    )
    assert count_b == 1, (
        f"restricted role + tenant B context: expected 1 row, got {count_b}"
    )

    await set_pg_rls_tenant(pg_session, "")
    count_none = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.tenant_attachments")
            )
        ).scalar_one()
    )
    assert count_none == 0, (
        f"restricted role + no context: expected 0 rows, got {count_none}; "
        "FORCE RLS should deny all access when no tenant context is set"
    )


@pytest.mark.asyncio
async def test_attachment_repository_get_rejects_wrong_tenant(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    """App-layer defense in depth: even under the OWNER role (which
    bypasses RLS), AttachmentRepository.get() must refuse a tenant_id that
    does not match the row — the explicit _clamp_tenant predicate, not RLS
    alone, is what this test pins."""
    tenant_owner = f"rls-att-owner-{uuid.uuid4().hex}"
    tenant_wrong = f"rls-att-wrong-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_owner
    )
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_wrong
    )

    attachment_id = uuid.uuid4()
    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=[
            (
                """
                INSERT INTO public.tenant_attachments (
                    attachment_id, tenant_id, channel, storage_backend,
                    storage_key, size_bytes, sha256_digest, status
                ) VALUES (
                    :attachment_id, :tenant_id, 'email', 's3',
                    :storage_key, 10, 'deadbeef', 'stored'
                )
                """,
                {
                    "attachment_id": attachment_id,
                    "tenant_id": tenant_owner,
                    "storage_key": f"{tenant_owner}/probe",
                },
            )
        ],
    )

    repository = AttachmentRepository(
        pg_session,
        data_protection=_dp_service(pg_session),
        blob_store=_RefusingBlobStore(),  # type: ignore[arg-type]
    )
    with pytest.raises(AttachmentNotFoundError):
        await repository.get(attachment_id, tenant_id=tenant_wrong)  # type: ignore[arg-type]


# ─── BC-3: encrypted-at-rest is app-layer, not just SSE ───────────────────


@requires_s3
@pytest.mark.asyncio
async def test_attachment_encrypted_at_rest_round_trip(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-att-encrypt-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )

    settings = Settings()
    blob_store = AttachmentBlobStore.from_settings(settings)
    data_protection = _dp_service(pg_session)
    repository = AttachmentRepository(
        pg_session, data_protection=data_protection, blob_store=blob_store
    )
    service = AttachmentStorageService(
        repository=repository,
        blob_store=blob_store,
        data_protection=data_protection,
        max_bytes=settings.ATTACHMENT_MAX_BYTES,
        retention_days=settings.ATTACHMENT_RETENTION_DAYS,
    )

    raw = b"%PDF-1.4 this is a fake invoice PDF body for BC-3. " * 20

    record: AttachmentRecord = await service.store(
        [raw],
        tenant_id=tenant_id,
        channel="email",
        external_message_id="msg-bc3",
        content_type_declared="application/pdf",
    )
    assert record.status == "stored"
    assert record.storage_key is not None

    try:
        # 1. The RAW S3 object — fetched directly, bypassing the repository
        #    entirely — must NOT be the plaintext, and must not even
        #    contain it as a substring (no partial plaintext leak).
        raw_object = blob_store.get(record.storage_key)
        assert raw_object != raw, (
            "S3 object is stored as plaintext — app-layer encryption is "
            "not applied; SSE-S3 alone is not the security boundary here"
        )
        assert raw not in raw_object, (
            "plaintext is a substring of the stored S3 object — partial "
            "plaintext leak even though the blobs differ"
        )

        # 2. AttachmentRepository.get() must decrypt back to the exact
        #    original bytes.
        fetched = await repository.get(record.attachment_id, tenant_id=tenant_id)
        assert fetched.content == raw, (
            "decrypted content does not match the original upload"
        )
    finally:
        blob_store.delete(record.storage_key)


class _FakeBlobStore:
    """In-memory stand-in for AttachmentBlobStore — validates the
    store()/get() orchestration (encrypt-before-put, decrypt-after-get)
    without requiring real S3 access, independent of the requires_s3 gate
    on BC-3."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, ciphertext: bytes) -> None:
        self._objects[key] = ciphertext

    def get(self, key: str) -> bytes:
        return self._objects[key]

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


@pytest.mark.asyncio
async def test_attachment_storage_round_trip_with_fake_blob_store(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    """Same orchestration as BC-3 (store -> raw-object-is-ciphertext ->
    get -> decrypts to original) but with an in-memory blob store, so it
    always runs regardless of S3 credential availability."""
    tenant_id = f"bc-att-fake-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )

    blob_store = _FakeBlobStore()
    data_protection = _dp_service(pg_session)
    repository = AttachmentRepository(
        pg_session,
        data_protection=data_protection,
        blob_store=blob_store,  # type: ignore[arg-type]
    )
    service = AttachmentStorageService(
        repository=repository,
        blob_store=blob_store,  # type: ignore[arg-type]
        data_protection=data_protection,
        max_bytes=10_000_000,
        retention_days=90,
    )

    raw = b"\x89PNG\r\n\x1a\n" + b"fake receipt photo bytes for round trip" * 10

    record = await service.store(
        [raw],
        tenant_id=tenant_id,
        channel="whatsapp",
        external_message_id="wamid-fake",
        content_type_declared="image/png",
    )
    assert record.status == "stored"
    assert record.content_type_sniffed == "image/png"
    assert record.storage_key is not None

    raw_object = blob_store.get(record.storage_key)
    assert raw_object != raw
    assert raw not in raw_object

    fetched = await repository.get(record.attachment_id, tenant_id=tenant_id)
    assert fetched.content == raw


# ─── BC-4: magic-byte reject — no S3 write is ever attempted ─────────────


@pytest.mark.asyncio
async def test_magic_byte_rejects_renamed_executable_without_s3_write(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-att-exe-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )

    data_protection = _dp_service(pg_session)
    blob_store = _RefusingBlobStore()
    repository = AttachmentRepository(
        pg_session,
        data_protection=data_protection,
        blob_store=blob_store,  # type: ignore[arg-type]
    )
    service = AttachmentStorageService(
        repository=repository,
        blob_store=blob_store,  # type: ignore[arg-type]
        data_protection=data_protection,
        max_bytes=10_000_000,
        retention_days=90,
    )

    exe_payload = b"MZ\x90\x00" + b"\x00" * 1024

    # If sniffing ever let this reach blob_store.put(), _RefusingBlobStore
    # raises AssertionError and the test fails — this is the proof, not
    # just the row's post-hoc status.
    record = await service.store(
        [exe_payload],
        tenant_id=tenant_id,
        channel="email",
        content_type_declared="application/pdf",
    )

    assert record.status == "rejected"
    assert record.storage_key is None
    assert record.rejection_reason is not None
    assert "Executable" in record.rejection_reason


# ─── BC-5: streaming size-abort — never buffers the full oversized input ──


def test_streaming_size_abort_does_not_drain_oversized_source() -> None:
    chunk = b"x" * 1024
    max_bytes = 4096
    pulls = {"count": 0}

    def _tripwire_chunks() -> Any:
        # An "infinite" source standing in for a malicious multi-GB body.
        # If read_bounded ever buffered the whole thing first and checked
        # afterward, this generator would never terminate and the test
        # would hang instead of failing — the early-abort property is
        # what keeps this test finite at all.
        while True:
            pulls["count"] += 1
            if pulls["count"] > 1000:
                raise AssertionError(
                    "read_bounded pulled far more chunks than needed to "
                    "exceed max_bytes — it is buffering before checking, "
                    "not aborting on the first chunk that crosses the cap"
                )
            yield chunk

    with pytest.raises(AttachmentTooLargeError) as excinfo:
        read_bounded(_tripwire_chunks(), max_bytes=max_bytes)

    expected_chunks_to_exceed = (max_bytes // len(chunk)) + 1
    assert pulls["count"] <= expected_chunks_to_exceed, (
        f"expected to abort within {expected_chunks_to_exceed} chunks, "
        f"pulled {pulls['count']}"
    )
    assert excinfo.value.bytes_read <= max_bytes + len(chunk)
    assert excinfo.value.max_bytes == max_bytes


# ─── BC-6: separate allow-lists (attachments admit images, KB does not) ──


def test_attachment_allowlist_is_separate_from_knowledge_upload_allowlist() -> None:
    assert "image/jpeg" in ATTACHMENT_ALLOWED_CONTENT_TYPES
    assert "image/png" in ATTACHMENT_ALLOWED_CONTENT_TYPES
    assert "image/jpeg" not in KNOWLEDGE_ALLOWED_TYPES, (
        "knowledge-upload allow-list must NOT be relaxed to admit images"
    )
    assert "image/png" not in KNOWLEDGE_ALLOWED_TYPES, (
        "knowledge-upload allow-list must NOT be relaxed to admit images"
    )
