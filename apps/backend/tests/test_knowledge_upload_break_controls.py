"""Break-control tests for document-upload + ingestion.

Verified properties:
  BC-1a  QUARANTINED upload is NOT returned by KnowledgeRuntime.retrieve
  BC-1b  Same doc BECOMES retrievable after review_status=APPROVED
  BC-2   Encryption round-trip: raw_content is UNREADABLE as plaintext at rest
  BC-3   Magic-byte type validation rejects .exe renamed .pdf
  BC-4   INDEX_FAILED surfaces after terminal reindex failure
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_protection.crypto import DataProtectionService, MasterKeyRing
from app.knowledge import (
    KnowledgeRuntime,
    derive_chunk_id,
    derive_vector_id,
)
from app.knowledge.embeddings import DEFAULT_EMBEDDING_DIMENSIONS
from app.tenant.file_ingestion import (
    KnowledgeUploadTypeError,
    parse_uploaded_document,
)
from app.knowledge.persistence import (
    KnowledgeChunkRecord,
    KnowledgeVectorRecord,
    PostgresKnowledgeRepository,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import (
    derive_knowledge_document_id,
)
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from tests.conftest import requires_postgres

_NOW = datetime(2026, 6, 16, 12, tzinfo=timezone.utc)
_TENANT = "tenant-upload-break-controls"
_INDEX = "bc_upload_test"
_PROVIDER = "openai"
_MODEL = "text-embedding-3-small"
_DIMS = DEFAULT_EMBEDDING_DIMENSIONS


# ── Shared helpers ───────────────────────────────────────────────────────────

class _FixedEmbeddingProvider:
    provider_name = _PROVIDER
    model_name = _MODEL
    dimensions = _DIMS

    def __init__(self, embedding: tuple[float, ...]) -> None:
        self._e = embedding

    async def embed_texts(
        self, *, tenant_id: str, texts: Sequence[str]
    ) -> tuple[tuple[float, ...], ...]:
        return tuple(self._e for _ in texts)


def _vec(y: float = 1.0) -> tuple[float, ...]:
    base = [0.0] * _DIMS
    base[1] = y
    mag = sum(v * v for v in base) ** 0.5
    return tuple(v / mag for v in base)


async def _seed_doc_with_vectors(
    session: AsyncSession,
    *,
    title: str,
    review_status: TenantKnowledgeReviewStatus,
    status: TenantKnowledgeDocumentStatus = TenantKnowledgeDocumentStatus.ACTIVE,
) -> TenantKnowledgeDocumentRecord:
    doc_id = derive_knowledge_document_id(
        tenant_id=_TENANT,
        title=title,
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    doc = TenantKnowledgeDocumentRecord(
        document_id=doc_id,
        tenant_id=_TENANT,
        title=title,
        content="Uploaded document extracted text for retrieval test.",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=status,
        review_status=review_status,
        version=1,
        uploaded_by="test-principal",
        vector_indexed_at=_NOW,
        created_at=_NOW,
    )
    repo = PostgresTenantConfigurationRepository(session)
    await repo.save_knowledge_document(doc, expected_tenant_id=_TENANT)

    content = f"{title} chunk 0"
    content_hash = f"{title}-0".encode("utf-8").hex()[:64]
    chunk_id = derive_chunk_id(
        tenant_id=_TENANT,
        document_id=doc_id,
        document_version=1,
        ordinal=0,
        content_hash=content_hash,
    )
    vector_id = derive_vector_id(
        tenant_id=_TENANT,
        chunk_id=chunk_id,
        provider=_PROVIDER,
        model=_MODEL,
        vector_index_name=_INDEX,
    )
    embedding = _vec(y=1.0)
    chunk = KnowledgeChunkRecord(
        chunk_id=chunk_id,
        tenant_id=_TENANT,
        document_id=doc_id,
        document_version=1,
        ordinal=0,
        content=content,
        content_hash=content_hash,
        token_count=4,
        char_start=0,
        char_end=len(content),
        is_current=True,
        indexed_at=_NOW,
        metadata={"document_title": title, "document_type": "sop"},
    )
    vector = KnowledgeVectorRecord(
        vector_id=vector_id,
        tenant_id=_TENANT,
        chunk_id=chunk_id,
        document_id=doc_id,
        document_version=1,
        provider=_PROVIDER,
        model=_MODEL,
        dimensions=_DIMS,
        vector_index_name=_INDEX,
        vector=embedding,
        is_current=True,
        indexed_at=_NOW,
        metadata={"document_title": title, "document_type": "sop"},
    )
    await PostgresKnowledgeRepository(session).replace_document_index(
        tenant_id=_TENANT,
        document_id=doc_id,
        document_version=1,
        vector_index_name=_INDEX,
        chunks=(chunk,),
        vectors=(vector,),
        expected_tenant_id=_TENANT,
    )
    return doc


def _runtime(session: AsyncSession) -> KnowledgeRuntime:
    return KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(session),
        tenant_configuration_repository=PostgresTenantConfigurationRepository(session),
        embedding_provider=_FixedEmbeddingProvider(_vec(y=1.0)),
        vector_index_name=_INDEX,
    )


def _dp_service(session: Any) -> DataProtectionService:
    return DataProtectionService(
        session,
        master_key_ring=MasterKeyRing(keys={"v1": b"a" * 32}, active_version="v1"),
    )


# ── BC-1a: QUARANTINED doc is NOT returned by retrieve ──────────────────────

@pytest.mark.asyncio
@requires_postgres
async def test_quarantined_upload_not_retrieved(
    pg_seed_session: AsyncSession,
) -> None:
    """BC-1a: an uploaded+indexed doc with review_status=QUARANTINED must be
    invisible to KnowledgeRuntime.retrieve — the AI cannot ground on it."""
    await _seed_doc_with_vectors(
        pg_seed_session,
        title="BC1a Quarantined Upload",
        review_status=TenantKnowledgeReviewStatus.QUARANTINED,
    )
    result = await _runtime(pg_seed_session).retrieve(
        tenant_id=_TENANT,
        query="BC1a Quarantined Upload",
        top_k=10,
    )
    retrieved_titles = [item.content for item in result.items]
    assert not any("BC1a Quarantined Upload" in t for t in retrieved_titles), (
        "QUARANTINED document was returned by retrieve — governance gate is broken"
    )


# ── BC-1b: Same doc BECOMES retrievable after review_status=APPROVED ────────

@pytest.mark.asyncio
@requires_postgres
async def test_approved_upload_is_retrieved(
    pg_seed_session: AsyncSession,
) -> None:
    """BC-1b: after review_status is promoted to APPROVED the doc is visible."""
    doc = await _seed_doc_with_vectors(
        pg_seed_session,
        title="BC1b Approved Upload",
        review_status=TenantKnowledgeReviewStatus.QUARANTINED,
    )
    repo = PostgresTenantConfigurationRepository(pg_seed_session)
    approved_doc = replace(doc, review_status=TenantKnowledgeReviewStatus.APPROVED)
    await repo.save_knowledge_document(approved_doc, expected_tenant_id=_TENANT)
    await pg_seed_session.flush()

    result = await _runtime(pg_seed_session).retrieve(
        tenant_id=_TENANT,
        query="BC1b Approved Upload",
        top_k=10,
    )
    assert result.items, (
        "APPROVED document was NOT returned by retrieve — governance gate blocks even approved"
    )
    assert all(
        item.document_review_status == "approved" for item in result.items
    ), "retrieve returned a chunk whose document_review_status is not 'approved'"


# ── BC-2: Encryption round-trip for upload raw_content ──────────────────────

@pytest.mark.asyncio
@requires_postgres
async def test_upload_raw_content_encryption_round_trip(
    pg_seed_session: AsyncSession,
) -> None:
    """BC-2: raw_content stored via _protect_upload_record must not be
    readable as plaintext and must decrypt to the original bytes.

    Uses a real Postgres session because DataProtectionService creates/stores
    DEKs in the data_protection_data_keys table (a real DB write).
    """
    raw = b"This is real document text that should be protected. " * 20
    tenant_id = _TENANT

    svc = _dp_service(pg_seed_session)

    # Simulate what _protect_upload_record does:
    encrypted = await svc.encrypt_bytes(
        raw,
        tenant_id=tenant_id,
        subject_id=None,
        field="tenant_knowledge_uploads.raw_content",
        tenant_scoped=True,
    )

    # 1. Encrypted blob must NOT be equal to the raw plaintext
    assert encrypted != raw, (
        "raw_content is stored as plaintext at rest — encryption is not applied"
    )
    # 2. Encrypted blob must not CONTAIN the plaintext as a substring
    assert raw not in encrypted, (
        "raw_content plaintext is a substring of the stored blob — partial plaintext leak"
    )
    # 3. Decrypt must recover the exact original bytes
    decrypted = await svc.decrypt_bytes(encrypted)
    assert decrypted == raw, (
        f"Decrypted raw_content does not match original: got {decrypted[:40]!r}"
    )


@pytest.mark.asyncio
@requires_postgres
async def test_document_content_encryption_round_trip(
    pg_seed_session: AsyncSession,
) -> None:
    """BC-2b: document content (extracted text) stored via _protect_document_record
    must also round-trip and not be readable as plaintext at rest."""
    content = "SOP content for encryption at rest verification. " * 10
    tenant_id = _TENANT

    svc = _dp_service(pg_seed_session)

    encrypted = await svc.encrypt_text(
        content,
        tenant_id=tenant_id,
        subject_id=None,
        field="tenant_knowledge_documents.content",
        tenant_scoped=True,
    )
    assert encrypted != content, "document content stored as plaintext at rest"
    assert content.encode("utf-8") not in encrypted.encode("utf-8"), (
        "document content plaintext is a substring of the stored ciphertext"
    )
    decrypted = await svc.decrypt_text(encrypted)
    assert decrypted == content


# ── BC-3: Magic-byte type validation rejects mismatched/malicious files ──────

def test_magic_byte_rejects_exe_renamed_as_pdf() -> None:
    """BC-3: Windows executable (MZ header) renamed to .pdf must be rejected."""
    exe_payload = b"MZ\x90\x00" + b"\x00" * 1024
    with pytest.raises(KnowledgeUploadTypeError):
        parse_uploaded_document(filename="malware.pdf", raw_bytes=exe_payload)


def test_magic_byte_rejects_arbitrary_binary() -> None:
    """BC-3b: arbitrary binary not matching any supported magic must be rejected."""
    arbitrary = bytes(b"\xff\xfe\xfd") + b"\x00" * 1024
    with pytest.raises(KnowledgeUploadTypeError):
        parse_uploaded_document(filename="binary.pdf", raw_bytes=arbitrary)


def test_magic_byte_accepts_valid_text() -> None:
    """BC-3c: valid UTF-8 plain text passes and returns text/plain."""
    txt = ("Valid document text for knowledge base upload. " * 5).encode("utf-8")
    ct, text_out = parse_uploaded_document(filename="notes.txt", raw_bytes=txt)
    assert ct == "text/plain"
    assert len(text_out) >= 50


# ── BC-4: INDEX_FAILED surfaces after terminal reindex failure ───────────────

@pytest.mark.asyncio
async def test_index_failed_persisted_on_terminal_failure() -> None:
    """BC-4: after all Celery retries are exhausted the document status must be
    set to INDEX_FAILED and last_index_error must be populated."""
    import app.workers.knowledge_tasks as knowledge_tasks

    doc_id = str(derive_knowledge_document_id(
        tenant_id="tenant-bc4",
        title="BC4 Terminal Failure",
        document_type=TenantKnowledgeDocumentType.SOP,
    ))

    original_doc = TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id="tenant-bc4",
            title="BC4 Terminal Failure",
            document_type=TenantKnowledgeDocumentType.SOP,
        ),
        tenant_id="tenant-bc4",
        title="BC4 Terminal Failure",
        content="some content",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        review_status=TenantKnowledgeReviewStatus.QUARANTINED,
        version=1,
        uploaded_by="test",
        vector_indexed_at=None,
        created_at=_NOW,
    )

    persisted: list[TenantKnowledgeDocumentRecord] = []
    failure_error = "embedding provider unreachable (BC-4 test)"

    async def _fake_persist_index_failed(
        *, document_id: str, tenant_id: str, error: str
    ) -> None:
        failed = replace(
            original_doc,
            status=TenantKnowledgeDocumentStatus.INDEX_FAILED,
            last_index_error=error[:4096],
        )
        persisted.append(failed)

    task_self = MagicMock()
    task_self.request.retries = 3  # at max_retries
    task_self.max_retries = 3

    # Celery bind=True stores the task as a bound method so .run is already bound
    # to the Celery task object.  Use __func__ to get the raw Python function and
    # call it with our mock as _self, bypassing Celery dispatch machinery.
    raw_fn = knowledge_tasks.reindex_knowledge_document.run.__func__

    # Patch the runtime coroutine to raise (simulating an indexing failure).
    # We do NOT patch _run_async itself — that would also block the subsequent
    # _persist_index_failed call inside the terminal-failure branch.
    async def _failing_runtime(**kwargs: object) -> dict[str, object]:
        raise Exception(failure_error)

    with patch.object(
        knowledge_tasks,
        "reindex_knowledge_document_runtime",
        _failing_runtime,
    ):
        with patch.object(
            knowledge_tasks,
            "_persist_index_failed",
            _fake_persist_index_failed,
        ):
            with pytest.raises(Exception, match="BC-4 test"):
                raw_fn(task_self, document_id=doc_id, tenant_id="tenant-bc4")

    assert persisted, (
        "INDEX_FAILED was never persisted — condition 5 (BC-4) violated: "
        "doc remains silently stuck in PENDING_INDEX"
    )
    final = persisted[-1]
    assert final.status == TenantKnowledgeDocumentStatus.INDEX_FAILED, (
        f"Expected INDEX_FAILED status, got {final.status!r}"
    )
    assert final.last_index_error is not None, "last_index_error not populated"
    assert failure_error in final.last_index_error
