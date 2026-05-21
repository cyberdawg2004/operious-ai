"""Session read endpoints — v1 transport layer (PR-D8).

Six read endpoints across the three apex record types:

* GET /sessions/{session_id}                → apex point read
* GET /sessions                              → apex page
* GET /sessions/{session_id}/events         → child events (parent-scoped)
* GET /events/{event_id}                    → event point read
* GET /sessions/{session_id}/correlations   → child correlations (parent-scoped)
* GET /correlations/{correlation_id}        → correlation point read

Sub-record reads inherit tenant scope from the owning session
(per PR-B7 contract) — the substrate's parent lookup handles
this transparently.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.session import (
    SessionCorrelationResponse,
    SessionCorrelationsPage,
    SessionEventResponse,
    SessionEventsPage,
    SessionResponse,
    SessionTimelineResponse,
    SessionsPage,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_session_repository
from app.session.contracts.results import ReconstructSessionResult
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
)
from app.session.persistence import (
    SessionCorrelationQuery,
    SessionEventQuery,
    SessionPersistenceProtocol,
    SessionQuery,
)
from app.session.runtime import SessionRuntime

router = APIRouter(tags=["session"])

_MIN_LIMIT = 1
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


def _parse_uuid_or_404(raw: str, *, kind: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": f"{kind}_not_found"},
        ) from exc


# ─── Sessions ────────────────────────────────────────────────────────────


@router.get(
    "/{session_id}/timeline",
    response_model=SessionTimelineResponse,
)
async def get_session_timeline(
    session_id: str,
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionTimelineResponse:
    sid = SessionId(_parse_uuid_or_404(session_id, kind="session"))
    record = await repo.get_session(
        sid, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "session_not_found"}
        )

    envelope = await SessionRuntime(persistence=repo).get_timeline(sid)
    if not envelope.is_ok or envelope.result is None:
        raise HTTPException(
            status_code=500, detail={"code": "timeline_read_failed"}
        )
    result = envelope.result
    if not isinstance(result, ReconstructSessionResult):
        raise HTTPException(
            status_code=500, detail={"code": "timeline_read_failed"}
        )
    return SessionTimelineResponse.from_timeline(
        result.timeline,
        fallback_tenant_id=expected_tenant_id,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
)
async def get_session(
    session_id: str,
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionResponse:
    sid = SessionId(_parse_uuid_or_404(session_id, kind="session"))
    record = await repo.get_session(
        sid, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "session_not_found"}
        )
    return SessionResponse.from_record(record)


@router.get(
    "/sessions",
    response_model=SessionsPage,
)
async def list_sessions(
    principal_id: str | None = Query(None),
    external_handle: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionsPage:
    query = SessionQuery(
        principal_id=principal_id,
        external_handle=external_handle,
        limit=limit,
        offset=offset,
    )
    page = await repo.list_sessions(
        query, expected_tenant_id=expected_tenant_id
    )
    return SessionsPage(
        items=[SessionResponse.from_record(r) for r in page.sessions],
        total=page.total,
    )


# ─── Events ──────────────────────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/events",
    response_model=SessionEventsPage,
)
async def list_events_for_session(
    session_id: str,
    from_sequence: int | None = Query(None, ge=0),
    to_sequence: int | None = Query(None, ge=0),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionEventsPage:
    sid = SessionId(_parse_uuid_or_404(session_id, kind="session"))
    query = SessionEventQuery(
        session_id=sid,
        from_sequence=from_sequence,
        to_sequence=to_sequence,
        limit=limit,
        offset=offset,
    )
    page = await repo.list_events(
        query, expected_tenant_id=expected_tenant_id
    )
    return SessionEventsPage(
        items=[SessionEventResponse.from_record(e) for e in page.events],
        total=page.total,
    )


@router.get(
    "/events/{event_id}",
    response_model=SessionEventResponse,
)
async def get_event(
    event_id: str,
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionEventResponse:
    eid = SessionEventId(_parse_uuid_or_404(event_id, kind="event"))
    record = await repo.get_event(
        eid, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "event_not_found"}
        )
    return SessionEventResponse.from_record(record)


# ─── Correlations ────────────────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/correlations",
    response_model=SessionCorrelationsPage,
)
async def list_correlations_for_session(
    session_id: str,
    external_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionCorrelationsPage:
    sid = SessionId(_parse_uuid_or_404(session_id, kind="session"))
    query = SessionCorrelationQuery(
        session_id=sid,
        external_id=external_id,
        limit=limit,
        offset=offset,
    )
    page = await repo.list_correlations(
        query, expected_tenant_id=expected_tenant_id
    )
    return SessionCorrelationsPage(
        items=[
            SessionCorrelationResponse.from_record(c)
            for c in page.correlations
        ],
        total=page.total,
    )


@router.get(
    "/correlations/{correlation_id}",
    response_model=SessionCorrelationResponse,
)
async def get_correlation(
    correlation_id: str,
    repo: SessionPersistenceProtocol = Depends(get_session_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionCorrelationResponse:
    cid = SessionCorrelationId(
        _parse_uuid_or_404(correlation_id, kind="correlation")
    )
    record = await repo.get_correlation(
        cid, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "correlation_not_found"}
        )
    return SessionCorrelationResponse.from_record(record)


__all__ = ["router"]
