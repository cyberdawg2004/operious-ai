"""Live conversation endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from app.api.v1.schemas.conversation import (
    ConversationMessageRequest,
    ConversationMessageResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_conversation_service
from app.services.conversation_service import (
    ConversationService,
    ConversationServiceError,
)

router = APIRouter(tags=["conversation"])


@router.post(
    "/{session_id}/message",
    response_model=ConversationMessageResponse,
)
async def submit_conversation_message(
    session_id: str,
    request: ConversationMessageRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationMessageResponse:
    try:
        return ConversationMessageResponse.from_submission(
            await service.submit_message(
                session_id=session_id,
                tenant_id=expected_tenant_id,
                content=request.content,
                expected_tenant_id=expected_tenant_id,
            )
        )
    except ConversationServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/stream")
async def stream_conversation(
    session_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: ConversationService = Depends(get_conversation_service),
) -> EventSourceResponse:
    try:
        await service.ensure_stream_access(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        )
    except ConversationServiceError as exc:
        raise _http_error(exc) from exc

    async def events() -> AsyncIterator[dict[str, str]]:
        async for event in service.stream_events(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        ):
            yield {
                "event": str(event.get("type") or "message"),
                "data": json.dumps(event, default=str),
            }

    return EventSourceResponse(events())


def _http_error(exc: ConversationServiceError) -> HTTPException:
    message = str(exc)
    status_code = status.HTTP_400_BAD_REQUEST
    code = "conversation_request_failed"
    if "not found" in message:
        status_code = status.HTTP_404_NOT_FOUND
        code = "session_not_found"
    elif "terminal" in message:
        status_code = status.HTTP_409_CONFLICT
        code = "session_terminal"
    elif "governance" in message or "dispatch" in message:
        status_code = status.HTTP_403_FORBIDDEN
        code = "conversation_governance_denied"
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


__all__ = ["router"]
