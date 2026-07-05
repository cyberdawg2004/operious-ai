"""Knowledge indexing worker tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, Protocol, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.core.logging import get_logger
from app.knowledge import (
    DeterministicKnowledgeChunker,
    KnowledgeIngestionResult,
    KnowledgeRuntime,
    as_document_id,
    build_embedding_provider,
)
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.queues import QUEUE_KNOWLEDGE_INDEXING
from app.tenant.enums import TenantKnowledgeDocumentStatus
from app.tenant.identity import TenantKnowledgeDocumentId
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.agents.governed.sop_contradiction import SOPContradictionAgent
from app.cognition.llm_factory import build_llm_client
from app.workers.celery_app import celery_app

_logger = get_logger(__name__)

_T = TypeVar("_T")


class KnowledgeIngestRuntimeProtocol(Protocol):
    async def ingest_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
    ) -> KnowledgeIngestionResult: ...


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="reindex_knowledge_document",
    queue=QUEUE_KNOWLEDGE_INDEXING,
    bind=True,
    ignore_result=True,
    max_retries=3,
    default_retry_delay=30,
)
def reindex_knowledge_document(
    _self: Any,
    *,
    document_id: str,
    tenant_id: str,
) -> dict[str, object]:
    """Re-index one tenant knowledge document after an approved SOP update."""
    try:
        return _run_async(
            reindex_knowledge_document_runtime(
                document_id=document_id,
                tenant_id=tenant_id,
            ),
            tenant_id=tenant_id,
        )
    except Exception as exc:
        if _self.request.retries >= _self.max_retries:
            # Terminal failure — all retries exhausted; surface INDEX_FAILED.
            _logger.error(
                "knowledge_reindex_terminal_failure",
                extra={
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "error": str(exc),
                },
            )
            try:
                _run_async(
                    _persist_index_failed(
                        document_id=document_id,
                        tenant_id=tenant_id,
                        error=str(exc),
                    ),
                    tenant_id=tenant_id,
                )
            except Exception as persist_exc:  # noqa: BLE001
                _logger.warning(
                    "knowledge_reindex_index_failed_persist_error",
                    extra={
                        "document_id": document_id,
                        "tenant_id": tenant_id,
                        "error": str(persist_exc),
                    },
                )
        raise


async def reindex_knowledge_document_runtime(
    *,
    document_id: str,
    tenant_id: str,
    session: AsyncSession | None = None,
    knowledge_runtime: KnowledgeIngestRuntimeProtocol | None = None,
) -> dict[str, object]:
    if not tenant_id.strip():
        raise ValueError("tenant_id must be non-empty")
    parsed_document_id = as_document_id(document_id)
    previous_tenant = get_current_tenant()
    set_current_tenant(tenant_id)
    try:
        if knowledge_runtime is not None:
            result = await knowledge_runtime.ingest_document(
                tenant_id=tenant_id,
                document_id=parsed_document_id,
            )
            return _result_payload(result)
        if session is not None:
            await _set_db_tenant_context(session, tenant_id)
            result = await _knowledge_runtime(session).ingest_document(
                tenant_id=tenant_id,
                document_id=parsed_document_id,
            )
            await session.commit()
            return _result_payload(result)

        session_factory = get_session_factory()
        async with session_factory() as owned_session:
            await _set_db_tenant_context(owned_session, tenant_id)
            result = await _knowledge_runtime(owned_session).ingest_document(
                tenant_id=tenant_id,
                document_id=parsed_document_id,
            )
            await owned_session.commit()
            return _result_payload(result)
    finally:
        set_current_tenant(previous_tenant)


async def _persist_index_failed(
    *,
    document_id: str,
    tenant_id: str,
    error: str,
) -> None:
    from dataclasses import replace as dc_replace

    parsed_document_id = as_document_id(document_id)
    session_factory = get_session_factory()
    async with session_factory() as session:
        await _set_db_tenant_context(session, tenant_id)
        repo = PostgresTenantConfigurationRepository(
            session,
            data_protection=_data_protection_service(session),
        )
        record = await repo.get_knowledge_document(
            parsed_document_id,
            expected_tenant_id=tenant_id,
        )
        if record is not None:
            failed_record = dc_replace(
                record,
                status=TenantKnowledgeDocumentStatus.INDEX_FAILED,
                last_index_error=error[:4096],
            )
            await repo.save_knowledge_document(
                failed_record,
                expected_tenant_id=tenant_id,
            )
            await session.commit()


def _knowledge_runtime(session: AsyncSession) -> KnowledgeRuntime:
    settings = get_settings()
    data_protection = _data_protection_service(session)
    tenant_config_repo = PostgresTenantConfigurationRepository(
        session,
        data_protection=data_protection,
    )
    return KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(
            session,
            data_protection=data_protection,
        ),
        tenant_configuration_repository=tenant_config_repo,
        embedding_provider=build_embedding_provider(settings),
        chunker=DeterministicKnowledgeChunker(
            target_size=settings.CHUNK_TARGET_SIZE,
            overlap=settings.CHUNK_OVERLAP,
            min_size=settings.CHUNK_MIN_SIZE,
        ),
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
        default_context_token_budget=settings.RAG_DEFAULT_CONTEXT_TOKEN_BUDGET,
        sop_contradiction_agent=SOPContradictionAgent(
            llm_client=build_llm_client(settings),
            tenant_configuration_repository=tenant_config_repo,
        ),
    )


def _data_protection_service(session: AsyncSession) -> DataProtectionService | None:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        return None
    return DataProtectionService.from_settings(
        session,
        settings,
        master_key_unwrap=build_master_key_unwrap(settings),
        legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
    )


async def _set_db_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": tenant_id},
    )


def _result_payload(result: KnowledgeIngestionResult) -> dict[str, object]:
    return {
        "status": "completed",
        "tenant_id": result.tenant_id,
        "document_id": str(result.document_id),
        "document_version": result.document_version,
        "chunk_count": result.chunk_count,
        "vector_count": result.vector_count,
        "vector_index_name": result.vector_index_name,
        "indexed_at": result.indexed_at.isoformat(),
    }


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            set_current_tenant(None)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            set_current_tenant(None)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("knowledge reindex coroutine returned no result")
    return results[0]


__all__ = [
    "reindex_knowledge_document",
    "reindex_knowledge_document_runtime",
]
