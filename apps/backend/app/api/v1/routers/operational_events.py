"""Canonical operational event read endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.operational_events import (
    OperationalEventPageResponse,
    OperationalReplayTraceResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_operational_event_service
from app.services.operational_event_service import OperationalEventService

router = APIRouter(tags=["operational-events"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 100


@router.get("", response_model=OperationalEventPageResponse)
async def list_operational_events(
    event_id: str | None = Query(default=None),
    operational_act: str | None = Query(default=None),
    substrate: str | None = Query(default=None),
    root_event_id: str | None = Query(default=None),
    parent_event_id: str | None = Query(default=None),
    governance_decision_id: str | None = Query(default=None),
    occurred_after_or_at: datetime | None = Query(default=None),
    occurred_before_or_at: datetime | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalEventService = Depends(get_operational_event_service),
) -> OperationalEventPageResponse:
    try:
        page = await service.list_events(
            tenant_id=expected_tenant_id,
            event_id=event_id,
            operational_act=operational_act,
            substrate=substrate,
            root_event_id=root_event_id,
            parent_event_id=parent_event_id,
            governance_decision_id=governance_decision_id,
            occurred_after_or_at=occurred_after_or_at,
            occurred_before_or_at=occurred_before_or_at,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_operational_event_query"},
        ) from exc
    return OperationalEventPageResponse.from_page(page)


@router.get("/replay", response_model=OperationalReplayTraceResponse)
async def load_operational_replay_trace(
    event_id: str | None = Query(default=None),
    root_event_id: str | None = Query(default=None),
    operational_act: str | None = Query(default=None),
    substrate: str | None = Query(default=None),
    governance_decision_id: str | None = Query(default=None),
    occurred_after_or_at: datetime | None = Query(default=None),
    occurred_before_or_at: datetime | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalEventService = Depends(get_operational_event_service),
) -> OperationalReplayTraceResponse:
    try:
        trace = await service.load_replay_trace(
            tenant_id=expected_tenant_id,
            event_id=event_id,
            root_event_id=root_event_id,
            operational_act=operational_act,
            substrate=substrate,
            governance_decision_id=governance_decision_id,
            occurred_after_or_at=occurred_after_or_at,
            occurred_before_or_at=occurred_before_or_at,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_operational_replay_query"},
        ) from exc
    return OperationalReplayTraceResponse.from_trace(trace)


__all__ = ["router"]
