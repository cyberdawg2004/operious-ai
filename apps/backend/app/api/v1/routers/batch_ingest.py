"""Batch-safe boundary ingestion endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas.ingress import (
    BatchIngestRequest,
    BatchIngestResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import (
    get_batch_ingest_service,
)
from app.services.batch_ingest_service import BatchIngestService

router = APIRouter(tags=["ingress"])


@router.post(
    "/ingest/batch",
    response_model=BatchIngestResponse,
    status_code=200,
)
async def batch_ingest(
    body: BatchIngestRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: BatchIngestService = Depends(get_batch_ingest_service),
) -> BatchIngestResponse:
    try:
        return await service.process_batch(
            items=body.items,
            tenant_id=expected_tenant_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "batch_ingest_failed"},
        ) from exc


__all__ = ["router"]
