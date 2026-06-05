#!/usr/bin/env python3
"""Dry-run-first job to re-embed tenant knowledge at the native dimension."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.data_protection.crypto import DataProtectionService  # noqa: E402
from app.db.url import build_database_engine_config  # noqa: E402
from app.knowledge.chunking import DeterministicKnowledgeChunker  # noqa: E402
from app.knowledge.embeddings import (  # noqa: E402
    DEFAULT_EMBEDDING_DIMENSIONS,
    KnowledgeEmbeddingProvider,
    build_embedding_provider,
)
from app.knowledge.persistence import PostgresKnowledgeRepository  # noqa: E402
from app.knowledge.runtime import KnowledgeRuntime  # noqa: E402
from app.tenant.db.models import TenantKnowledgeDocumentRow  # noqa: E402
from app.tenant.persistence import PostgresTenantConfigurationRepository  # noqa: E402

ANKER_TENANT_ID: Final[str] = "anker-pilot"
ANKER_DOCUMENT_TITLES: Final[tuple[str, ...]] = (
    "Anker Pilot Demo - Charging Issue Policy",
    "Anker Pilot Demo - Returns And Refund Policy",
    "Anker Pilot Demo - Warranty Terms",
    "Anker Pilot Demo - Escalation Matrix",
    "Anker Pilot Demo - Product Defect Classification Guide",
)


@dataclass(frozen=True, slots=True)
class VectorState:
    current_vectors: int
    dimensions: tuple[int, ...]
    native_vectors: int
    native_dimensions: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReembedRecordReport:
    document_id: str
    title: str
    before: VectorState
    after: VectorState
    changed: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["before"] = self.before.to_dict()
        payload["after"] = self.after.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class ReembedSummary:
    tenant_id: str
    dry_run: bool
    provider: str
    model: str
    target_dimensions: int
    vector_index_name: str
    scanned_documents: int
    changed_documents: int
    records: tuple[ReembedRecordReport, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["records"] = [record.to_dict() for record in self.records]
        return payload


async def run_reembed(
    session: AsyncSession,
    *,
    embedding_provider: KnowledgeEmbeddingProvider | None = None,
    data_protection: DataProtectionService | None = None,
    tenant_id: str = ANKER_TENANT_ID,
    titles: tuple[str, ...] = ANKER_DOCUMENT_TITLES,
    vector_index_name: str | None = None,
    execute: bool = False,
) -> ReembedSummary:
    """Inspect or re-embed matching tenant knowledge documents.

    ``execute=False`` does not call the embedding provider. ``execute=True``
    re-ingests each matching document through ``KnowledgeRuntime`` so chunks,
    JSONB vectors, row metadata, and the native pgvector copy are refreshed by
    the same production path used by normal indexing.
    """

    settings = get_settings()
    provider = embedding_provider or build_embedding_provider(settings)
    target_dimensions = provider.dimensions
    if target_dimensions != DEFAULT_EMBEDDING_DIMENSIONS:
        raise ValueError(
            "re-embed provider dimension must match native pgvector dimension "
            f"{DEFAULT_EMBEDDING_DIMENSIONS}; got {target_dimensions}"
        )
    index_name = vector_index_name or settings.VECTOR_DEFAULT_INDEX
    await _set_tenant_context(session, tenant_id)
    documents = await _matching_documents(session, tenant_id=tenant_id, titles=titles)

    runtime: KnowledgeRuntime | None = None
    if execute:
        runtime = KnowledgeRuntime(
            repository=PostgresKnowledgeRepository(
                session,
                data_protection=data_protection,
            ),
            tenant_configuration_repository=PostgresTenantConfigurationRepository(
                session,
                data_protection=data_protection,
            ),
            embedding_provider=provider,
            chunker=DeterministicKnowledgeChunker(
                target_size=settings.CHUNK_TARGET_SIZE,
                overlap=settings.CHUNK_OVERLAP,
                min_size=settings.CHUNK_MIN_SIZE,
            ),
            vector_index_name=index_name,
            default_context_token_budget=settings.RAG_DEFAULT_CONTEXT_TOKEN_BUDGET,
        )

    reports: list[ReembedRecordReport] = []
    for document in documents:
        before = await _current_vector_state(
            session,
            tenant_id=tenant_id,
            document_id=str(document.document_id),
            vector_index_name=index_name,
        )
        if execute:
            assert runtime is not None
            await runtime.ingest_document(
                tenant_id=tenant_id,
                document_id=document.document_id,
            )
            await session.flush()
        after = await _current_vector_state(
            session,
            tenant_id=tenant_id,
            document_id=str(document.document_id),
            vector_index_name=index_name,
        )
        reports.append(
            ReembedRecordReport(
                document_id=str(document.document_id),
                title=str(document.title),
                before=before,
                after=after,
                changed=before != after,
            )
        )

    return ReembedSummary(
        tenant_id=tenant_id,
        dry_run=not execute,
        provider=provider.provider_name,
        model=provider.model_name,
        target_dimensions=target_dimensions,
        vector_index_name=index_name,
        scanned_documents=len(documents),
        changed_documents=sum(1 for report in reports if report.changed),
        records=tuple(reports),
    )


async def _matching_documents(
    session: AsyncSession,
    *,
    tenant_id: str,
    titles: tuple[str, ...],
) -> tuple[TenantKnowledgeDocumentRow, ...]:
    stmt = (
        select(TenantKnowledgeDocumentRow)
        .where(TenantKnowledgeDocumentRow.tenant_id == tenant_id)
        .order_by(TenantKnowledgeDocumentRow.title)
    )
    if titles:
        stmt = stmt.where(TenantKnowledgeDocumentRow.title.in_(titles))
    return tuple((await session.execute(stmt)).scalars().all())


async def _current_vector_state(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: str,
    vector_index_name: str,
) -> VectorState:
    result = await session.execute(
        text(
            """
            SELECT
                dimensions,
                CASE
                    WHEN embedding IS NULL THEN NULL
                    ELSE vector_dims(embedding)
                END AS native_dimensions
            FROM tenant_knowledge_vectors
            WHERE tenant_id = :tenant_id
              AND document_id = CAST(:document_id AS uuid)
              AND vector_index_name = :vector_index_name
              AND is_current IS TRUE
            """
        ),
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "vector_index_name": vector_index_name,
        },
    )
    rows = tuple(result.mappings().all())
    native_dimensions = tuple(
        sorted(
            {
                int(row["native_dimensions"])
                for row in rows
                if row["native_dimensions"] is not None
            }
        )
    )
    return VectorState(
        current_vectors=len(rows),
        dimensions=tuple(sorted({int(row["dimensions"]) for row in rows})),
        native_vectors=sum(1 for row in rows if row["native_dimensions"] is not None),
        native_dimensions=native_dimensions,
    )


async def _set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


async def _amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Re-embed tenant knowledge into the native pgvector dimension."
    )
    parser.add_argument("--tenant-id", default=ANKER_TENANT_ID)
    parser.add_argument(
        "--title",
        action="append",
        dest="titles",
        help="Document title to re-embed. May be passed more than once.",
    )
    parser.add_argument("--vector-index-name", default=None)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Persist the re-embed. Omit for dry-run inspection.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    engine_config = build_database_engine_config(
        settings.database_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    engine = create_async_engine(
        engine_config.async_url,
        future=True,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    try:
        async with session_factory() as session:
            data_protection = DataProtectionService.from_settings(session, settings)
            summary = await run_reembed(
                session,
                embedding_provider=build_embedding_provider(settings),
                data_protection=data_protection,
                tenant_id=args.tenant_id,
                titles=tuple(args.titles or ANKER_DOCUMENT_TITLES),
                vector_index_name=args.vector_index_name,
                execute=args.execute,
            )
            if args.execute:
                await session.commit()
            else:
                await session.rollback()
            print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    finally:
        await engine.dispose()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
