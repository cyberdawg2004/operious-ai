"""Break-control tests for PR-B2 — vision wiring for stored attachments.

Verified properties:
  BC-1  Backward-compat: a plain-string DiagnosticLLMMessage.content
        renders to a bare string for Anthropic and for the audit
        snapshot — completely unchanged from pre-B2 behavior. (The
        existing diagnostic test suite is run unmodified as the broader
        proof of this — see the full-suite run in the PR.)
  BC-2  Image/document blocks render to the correct Anthropic
        content-block array shape.
  BC-3  Audit redaction: the snapshot used for CognitionAuditRecord
        .prompt_full contains {type, attachment_id, sha256} for an
        image/document block and NEVER the base64 payload — and the
        reference resolves back to the real (encrypted) stored
        attachment via AttachmentRepository.get().
  BC-4  Size/page/count caps: an over-5MiB image is skipped from vision;
        a >20-page PDF is skipped; a 5th attachment_id is never even
        fetched.
  BC-5  THE PROOF (requires_live_anthropic + real S3): a real diagnostic
        call against a real Claude reads a unique order number rendered
        as pixels in a synthetic invoice PNG and includes it in the
        response. Negative control: omitting the attachment, the model
        never produces that value.
"""

from __future__ import annotations

import base64
import io
import os
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.attachments.identity import AttachmentId
from app.attachments.records import AttachmentRecord
from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.attachments.storage_service import AttachmentStorageService
from app.cognition.diagnostic_runtime import (
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
    _full_prompt_snapshot,  # pyright: ignore[reportPrivateUsage]
)
from app.cognition.llm import (
    AnthropicMessagesClient,
    DeterministicDiagnosticLLMClient,
    DiagnosticImageBlock,
    DiagnosticLLMMessage,
    DiagnosticTextBlock,
    message_text,
    to_anthropic_content,
)
from app.core.config import Settings
from app.data_protection.crypto import DataProtectionService
from app.knowledge.models import KnowledgeRetrievalResult
from tests._png_text_renderer import render_text_png
from tests.conftest import (
    LIVE_EXTERNAL_TESTS_ENV,
    live_external_tests_enabled,
    requires_postgres,
)

pytestmark = [requires_postgres]

requires_s3 = pytest.mark.skipif(
    not (
        live_external_tests_enabled()
        and os.environ.get("ATTACHMENTS_S3_BUCKET")
    ),
    reason=(
        f"requires {LIVE_EXTERNAL_TESTS_ENV}=1 and ATTACHMENTS_S3_BUCKET "
        "(+ region/credentials) pointed at a real S3 bucket to exercise "
        "the real-S3 break-controls."
    ),
)
requires_live_anthropic = pytest.mark.skipif(
    not (
        live_external_tests_enabled() and os.environ.get("ANTHROPIC_API_KEY")
    ),
    reason=(
        f"requires {LIVE_EXTERNAL_TESTS_ENV}=1 and ANTHROPIC_API_KEY "
        "pointed at a real Anthropic account to exercise the live vision "
        "break-control — the deterministic test client never looks at "
        "bytes, so only a real model call can prove vision wiring "
        "actually works."
    ),
)

_ORDER_NUMBER = "ZX-88421-QQ"


class _FakeKnowledgeRuntime:
    async def retrieve(
        self, *, tenant_id: str, query: str, top_k: int, max_tokens: int
    ) -> KnowledgeRetrievalResult:
        _ = (top_k, max_tokens)
        return KnowledgeRetrievalResult(
            tenant_id=tenant_id,
            query=query,
            items=(),
            citations=(),
            budget_decisions=(),
            total_tokens=0,
            vector_index_name="vision-bc-test",
        )


class _UnusedUsagePersistence:
    pass


class _CountingAttachmentRepositoryStub:
    """Records every attachment_id .get() is called with, without
    touching Postgres/S3 — used to prove the per-call cap stops fetching
    after the Nth attachment."""

    def __init__(self, record: AttachmentRecord) -> None:
        self._record = record
        self.requested_ids: list[AttachmentId] = []

    async def get(self, attachment_id: AttachmentId, *, tenant_id: str) -> AttachmentRecord:
        _ = tenant_id
        self.requested_ids.append(attachment_id)
        return self._record


def _fake_record(
    *,
    content: bytes,
    content_type_sniffed: str,
    tenant_id: str = "tenant-vision-bc",
) -> AttachmentRecord:
    return AttachmentRecord(
        attachment_id=AttachmentId(uuid.uuid4()),
        tenant_id=tenant_id,
        channel="email",
        external_message_id=None,
        conversation_id=None,
        storage_backend="s3",
        storage_key="tenant-vision-bc/fake",
        content_type_declared=content_type_sniffed,
        content_type_sniffed=content_type_sniffed,
        size_bytes=len(content),
        sha256_digest="deadbeef" * 8,
        status="stored",
        rejection_reason=None,
        created_at=datetime.now(timezone.utc),
        retention_expires_at=None,
        content=content,
    )


def _blank_pdf(page_count: int) -> bytes:
    import pypdf

    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def _ensure_tenant_row(
    *,
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    tenant_id: str,
) -> None:
    statement = (
        "INSERT INTO public.tenants (tenant_id, status) "
        "VALUES (:tenant_id, 'active') ON CONFLICT (tenant_id) DO NOTHING"
    )
    if pg_seed_engine is None:
        await pg_session.execute(text(statement), {"tenant_id": tenant_id})
        await pg_session.commit()
        return
    async with pg_seed_engine.begin() as connection:
        await connection.execute(text(statement), {"tenant_id": tenant_id})


def _runtime(
    *,
    attachment_repository: Any,
    llm_client: Any = None,
    config: DiagnosticCognitionRuntimeConfig | None = None,
) -> DiagnosticCognitionRuntime:
    return DiagnosticCognitionRuntime(
        knowledge_runtime=cast(Any, _FakeKnowledgeRuntime()),
        llm_client=llm_client or DeterministicDiagnosticLLMClient(),
        usage_persistence=cast(Any, _UnusedUsagePersistence()),
        attachment_repository=attachment_repository,
        config=config,
    )


# ─── BC-1: backward-compat — bare string is untouched by both renderers ──


def test_text_only_content_renders_as_bare_string_for_anthropic() -> None:
    assert to_anthropic_content("plain ticket text") == "plain ticket text"


def test_text_only_content_snapshot_is_unchanged() -> None:
    message = DiagnosticLLMMessage(role="user", content="plain ticket text")
    snapshot = _full_prompt_snapshot(system_prompt="sys", messages=(message,))
    assert '"content":"plain ticket text"' in snapshot


def test_message_text_is_identity_for_string_content() -> None:
    assert message_text("plain ticket text") == "plain ticket text"


# ─── BC-2: block rendering shape ──────────────────────────────────────────


def test_image_and_text_blocks_render_to_anthropic_array() -> None:
    blocks = (
        DiagnosticImageBlock(
            media_type="image/png",
            base64_data="QkFTRTY0",
            attachment_id="attach-1",
            sha256_digest="abc123",
        ),
        DiagnosticTextBlock(text="What is the order number?"),
    )
    rendered = to_anthropic_content(blocks)
    assert rendered == [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "QkFTRTY0",
            },
        },
        {"type": "text", "text": "What is the order number?"},
    ]


def test_message_text_drops_image_blocks_keeps_text() -> None:
    blocks = (
        DiagnosticImageBlock(
            media_type="image/png",
            base64_data="QkFTRTY0",
            attachment_id="attach-1",
            sha256_digest="abc123",
        ),
        DiagnosticTextBlock(text="ticket body"),
    )
    assert message_text(blocks) == "ticket body"


# ─── BC-3: audit redaction — no bytes, reference resolves ────────────────


def test_audit_snapshot_redacts_image_bytes_but_keeps_reference() -> None:
    base64_payload = base64.b64encode(b"totally-not-a-real-image" * 50).decode("ascii")
    message = DiagnosticLLMMessage(
        role="user",
        content=(
            DiagnosticImageBlock(
                media_type="image/png",
                base64_data=base64_payload,
                attachment_id="attach-redact-1",
                sha256_digest="sha-redact-1",
            ),
            DiagnosticTextBlock(text="ticket body"),
        ),
    )
    snapshot = _full_prompt_snapshot(system_prompt="sys", messages=(message,))
    assert base64_payload not in snapshot, (
        "the audit snapshot must never contain the raw base64 payload"
    )
    assert "attach-redact-1" in snapshot
    assert "sha-redact-1" in snapshot


@requires_s3
@pytest.mark.asyncio
async def test_audit_reference_resolves_to_real_stored_attachment(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-vision-audit-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    settings = Settings()
    blob_store = AttachmentBlobStore.from_settings(settings)
    data_protection = DataProtectionService.from_settings(pg_session, settings)
    repository = AttachmentRepository(
        pg_session, data_protection=data_protection, blob_store=blob_store
    )
    storage_service = AttachmentStorageService.from_settings(
        settings,
        repository=repository,
        blob_store=blob_store,
        data_protection=data_protection,
    )
    png_bytes = render_text_png(f"ORDER #{_ORDER_NUMBER}")
    record = await storage_service.store(
        [png_bytes], tenant_id=tenant_id, channel="email", content_type_declared="image/png"
    )
    assert record.status == "stored"

    runtime = _runtime(attachment_repository=repository)
    snapshot = await runtime.load_reasoning_snapshot(
        tenant_id=tenant_id,
        execution_id="exec-audit",
        dispatch_id="dispatch-audit",
        session_id="session-audit",
        content="Customer asks about their order.",
        attachment_ids=(str(record.attachment_id),),
    )
    full_snapshot = _full_prompt_snapshot(
        system_prompt=snapshot.system_prompt, messages=snapshot.messages
    )
    encoded = base64.b64encode(png_bytes).decode("ascii")
    assert encoded not in full_snapshot, (
        "prompt_full (the persisted audit field) must never contain the "
        "raw image bytes"
    )
    assert str(record.attachment_id) in full_snapshot
    assert record.sha256_digest in full_snapshot

    # The reference resolves: the SAME attachment_id fetches the SAME
    # bytes that were actually sent to the model.
    refetched = await repository.get(record.attachment_id, tenant_id=tenant_id)
    assert refetched.content == png_bytes

    blob_store.delete(record.storage_key)  # type: ignore[arg-type]


# ─── BC-4: caps ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oversized_image_is_skipped_from_vision() -> None:
    config = DiagnosticCognitionRuntimeConfig(max_image_bytes_for_vision=1_000)
    runtime = _runtime(attachment_repository=None, config=config)
    record = _fake_record(content=b"x" * 2_000, content_type_sniffed="image/png")
    block = runtime._build_block(record)  # noqa: SLF001 — testing the unit directly  # pyright: ignore[reportPrivateUsage]
    assert block is None


@pytest.mark.asyncio
async def test_oversized_pdf_page_count_is_skipped_from_vision() -> None:
    config = DiagnosticCognitionRuntimeConfig(max_pdf_pages_for_vision=20)
    runtime = _runtime(attachment_repository=None, config=config)
    too_long_pdf = _blank_pdf(25)
    record = _fake_record(content=too_long_pdf, content_type_sniffed="application/pdf")
    block = runtime._build_block(record)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert block is None


@pytest.mark.asyncio
async def test_pdf_within_page_cap_is_not_skipped() -> None:
    config = DiagnosticCognitionRuntimeConfig(max_pdf_pages_for_vision=20)
    runtime = _runtime(attachment_repository=None, config=config)
    short_pdf = _blank_pdf(3)
    record = _fake_record(content=short_pdf, content_type_sniffed="application/pdf")
    block = runtime._build_block(record)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert block is not None


@pytest.mark.asyncio
async def test_fifth_attachment_is_never_fetched() -> None:
    config = DiagnosticCognitionRuntimeConfig(max_attachments_per_call=4)
    record = _fake_record(content=b"\x89PNG\r\n\x1a\n" + b"x" * 100, content_type_sniffed="image/png")
    stub = _CountingAttachmentRepositoryStub(record)
    runtime = _runtime(attachment_repository=cast(Any, stub), config=config)
    five_ids: Sequence[str] = tuple(str(uuid.uuid4()) for _ in range(5))

    await runtime._load_attachment_blocks(tuple(five_ids), tenant_id="tenant-cap")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert len(stub.requested_ids) == 4, (
        f"expected exactly 4 attachments fetched (the cap), got {len(stub.requested_ids)}"
    )


@pytest.mark.asyncio
async def test_docx_and_text_attachments_are_skipped_not_vision_eligible() -> None:
    runtime = _runtime(attachment_repository=None)
    docx_record = _fake_record(
        content=b"PK\x03\x04fake-docx",
        content_type_sniffed=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )
    text_record = _fake_record(content=b"plain text body", content_type_sniffed="text/plain")
    assert runtime._build_block(docx_record) is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert runtime._build_block(text_record) is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


# ─── BC-5: THE PROOF — a real model reads pixels, plus negative control ──


@requires_live_anthropic
@requires_s3
@pytest.mark.asyncio
async def test_live_diagnostic_call_reads_order_number_from_image(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-vision-live-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    settings = Settings()
    blob_store = AttachmentBlobStore.from_settings(settings)
    data_protection = DataProtectionService.from_settings(pg_session, settings)
    repository = AttachmentRepository(
        pg_session, data_protection=data_protection, blob_store=blob_store
    )
    storage_service = AttachmentStorageService.from_settings(
        settings,
        repository=repository,
        blob_store=blob_store,
        data_protection=data_protection,
    )
    png_bytes = render_text_png(f"ORDER #{_ORDER_NUMBER}")
    record = await storage_service.store(
        [png_bytes], tenant_id=tenant_id, channel="email", content_type_declared="image/png"
    )
    assert record.status == "stored"

    llm_client = AnthropicMessagesClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model=settings.ANTHROPIC_DEFAULT_MODEL,
    )
    runtime = _runtime(attachment_repository=repository, llm_client=llm_client)
    ticket_text = (
        "Customer wrote: 'Can you confirm the order number shown on my "
        "attached invoice image?' Carefully read any text visible in the "
        "attached image and state the exact order number in your summary "
        "and reasoning."
    )

    try:
        # With the attachment: the model must read and report the number.
        snapshot_with_image = await runtime.load_reasoning_snapshot(
            tenant_id=tenant_id,
            execution_id="exec-live-with-image",
            dispatch_id="dispatch-live-1",
            session_id="session-live",
            content=ticket_text,
            attachment_ids=(str(record.attachment_id),),
        )
        completion_with_image = await runtime.complete_reasoning_snapshot(
            snapshot_with_image
        )
        assert _ORDER_NUMBER in completion_with_image.text, (
            "model response did not contain the order number rendered as "
            f"pixels in the attached image: {completion_with_image.text!r}"
        )

        # Negative control: same ticket, no attachment — the model has no
        # way to know this value and must not produce it.
        snapshot_without_image = await runtime.load_reasoning_snapshot(
            tenant_id=tenant_id,
            execution_id="exec-live-without-image",
            dispatch_id="dispatch-live-2",
            session_id="session-live",
            content=ticket_text,
            attachment_ids=(),
        )
        completion_without_image = await runtime.complete_reasoning_snapshot(
            snapshot_without_image
        )
        assert _ORDER_NUMBER not in completion_without_image.text, (
            "model produced the order number WITHOUT the attachment — "
            "negative control failed (possible hallucination/leak): "
            f"{completion_without_image.text!r}"
        )
    finally:
        blob_store.delete(record.storage_key)  # type: ignore[arg-type]
