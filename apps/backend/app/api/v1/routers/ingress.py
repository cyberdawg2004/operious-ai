"""Ticket ingress write endpoint (PR-W1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas.ingress import (
    TicketIngressRequest,
    TicketIngressResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_ticket_ingress_service
from app.services.ticket_ingress_service import (
    TicketIngressService,
    TicketIngressServiceError,
)

router = APIRouter(tags=["ingress"])


@router.post("/ingress", response_model=TicketIngressResponse)
async def create_ticket_ingress(
    request: TicketIngressRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TicketIngressService = Depends(get_ticket_ingress_service),
) -> TicketIngressResponse:
    try:
        result = await service.process(
            external_id=request.external_id,
            channel=request.channel,
            raw_content=request.raw_content,
            language_code=request.language_code,
            expected_tenant_id=expected_tenant_id,
        )
    except TicketIngressServiceError as exc:
        raise HTTPException(
            status_code=500, detail={"code": "ticket_ingress_failed"}
        ) from exc
    return TicketIngressResponse(
        ingress_id=result.ingress_id,
        canonical_envelope_id=result.canonical_envelope_id,
    )


__all__ = ["router"]
