"""Tenant knowledge ingestion and retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.schemas.knowledge import (
    KnowledgeIngestionResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_knowledge_service
from app.knowledge.exceptions import (
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentNotIndexableError,
    KnowledgeError,
)
from app.knowledge.identity import as_document_id
from app.services.knowledge_service import KnowledgeService

router = APIRouter(tags=["knowledge"])


@router.post(
    "/documents/{document_id}/ingest",
    response_model=KnowledgeIngestionResponse,
)
async def ingest_knowledge_document(
    document_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeIngestionResponse:
    try:
        result = await service.ingest_document(
            tenant_id=expected_tenant_id,
            document_id=as_document_id(document_id),
        )
    except (ValueError, KnowledgeDocumentNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "knowledge_document_not_found"},
        ) from exc
    except KnowledgeDocumentNotIndexableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "knowledge_document_not_indexable"},
        ) from exc
    except KnowledgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "knowledge_ingestion_failed"},
        ) from exc
    return KnowledgeIngestionResponse.from_result(result)


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeSearchResponse:
    result = await service.retrieve(
        tenant_id=expected_tenant_id,
        query=request.query,
        top_k=request.top_k,
        max_tokens=request.max_tokens,
        max_chunks_per_document=request.max_chunks_per_document,
        min_score=request.min_score,
    )
    return KnowledgeSearchResponse.from_result(result)


__all__ = ["router"]
