"""Deterministic tenant knowledge identity primitives."""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import coerce_tenant_id
from app.tenant.identity import TenantKnowledgeDocumentId

KnowledgeChunkId = NewType("KnowledgeChunkId", uuid.UUID)
KnowledgeVectorId = NewType("KnowledgeVectorId", uuid.UUID)

_CHUNK_NAMESPACE: uuid.UUID = uuid.UUID(
    "5a000f1c-0001-4001-8001-000000000001"
)
_VECTOR_NAMESPACE: uuid.UUID = uuid.UUID(
    "5a000f1c-0002-4002-8002-000000000002"
)


def derive_chunk_id(
    *,
    tenant_id: str,
    document_id: TenantKnowledgeDocumentId,
    document_version: int,
    ordinal: int,
    content_hash: str,
) -> KnowledgeChunkId:
    tenant = coerce_tenant_id(tenant_id)
    if document_version < 1:
        raise ValueError("document_version must be >= 1")
    if ordinal < 0:
        raise ValueError("ordinal must be >= 0")
    if not content_hash:
        raise ValueError("content_hash must be non-empty")
    seed = (
        f"{tenant}|{document_id}|v{document_version}|"
        f"{ordinal}|{content_hash}"
    )
    return KnowledgeChunkId(uuid.uuid5(_CHUNK_NAMESPACE, seed))


def derive_vector_id(
    *,
    tenant_id: str,
    chunk_id: KnowledgeChunkId,
    provider: str,
    model: str,
    vector_index_name: str,
) -> KnowledgeVectorId:
    tenant = coerce_tenant_id(tenant_id)
    provider_text = _normalize_identity_text(provider, "provider")
    model_text = _normalize_identity_text(model, "model")
    index_text = _normalize_identity_text(
        vector_index_name, "vector_index_name"
    )
    seed = f"{tenant}|{chunk_id}|{provider_text}|{model_text}|{index_text}"
    return KnowledgeVectorId(uuid.uuid5(_VECTOR_NAMESPACE, seed))


def as_chunk_id(value: uuid.UUID | str) -> KnowledgeChunkId:
    return KnowledgeChunkId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_vector_id(value: uuid.UUID | str) -> KnowledgeVectorId:
    return KnowledgeVectorId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_document_id(value: uuid.UUID | str) -> TenantKnowledgeDocumentId:
    return TenantKnowledgeDocumentId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def _normalize_identity_text(raw: str, field_name: str) -> str:
    text = raw.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


__all__ = [
    "KnowledgeChunkId",
    "KnowledgeVectorId",
    "as_chunk_id",
    "as_document_id",
    "as_vector_id",
    "derive_chunk_id",
    "derive_vector_id",
]
