"""Conversation Inbox endpoints — manager-facing read-only view.

Two endpoints:
    GET /inbox               → paginated conversation list (inbox rows)
    GET /inbox/{session_id}  → full thread with governance context inline

All substrate-aware logic lives in InboxService (app.services.inbox_service).
This router only calls the service and projects domain records to wire schemas.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.inbox import (
    InboxConversationsPageResponse,
    InboxThreadResponse,
)
from app.dependencies.authority import (
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.services import get_inbox_service
from app.services.inbox_service import (
    InboxService,
    InboxSessionNotFoundError,
    _parse_lifecycle_phase,
)

router = APIRouter(tags=["inbox"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


@router.get(
    "",
    response_model=InboxConversationsPageResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def list_inbox_conversations(
    phase: str | None = Query(None),
    channel: str | None = Query(None),
    customer_identity_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    service: InboxService = Depends(get_inbox_service),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> InboxConversationsPageResponse:
    if phase is not None:
        lifecycle_phase = _parse_lifecycle_phase(phase)
        if lifecycle_phase is None:
            raise HTTPException(
                status_code=400, detail={"code": "invalid_lifecycle_phase"}
            )
    else:
        lifecycle_phase = None

    page = await service.list_conversations(
        expected_tenant_id=expected_tenant_id,
        lifecycle_phase=lifecycle_phase,
        channel=channel,
        customer_identity_id=customer_identity_id,
        limit=limit,
        offset=offset,
    )
    return InboxConversationsPageResponse.from_domain(page)


@router.get(
    "/{session_id}",
    response_model=InboxThreadResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def get_inbox_thread(
    session_id: str,
    include_siblings: bool = Query(
        False,
        description=(
            "If true and session has a confirmed cross-channel identity, "
            "include messages from sibling sessions (same customer_identity_id)."
        ),
    ),
    service: InboxService = Depends(get_inbox_service),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> InboxThreadResponse:
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "session_not_found"}
        ) from exc

    try:
        thread = await service.get_thread(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            include_siblings=include_siblings,
        )
    except InboxSessionNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "session_not_found"}
        ) from exc
    return InboxThreadResponse.from_domain(thread)


__all__ = ["router"]
