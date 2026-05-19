"""Boundary read endpoints — v1 transport layer (PR-D6).

Four read endpoints across the two apex record types:

* ``GET /ingress/{ingress_id}`` — one ingress record by id.
* ``GET /ingress``              — paginated ingress list.
* ``GET /egress/{egress_id}``   — one egress record by id.
* ``GET /egress``               — paginated egress list.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.boundary import (
    BoundaryEgressPage,
    BoundaryEgressResponse,
    BoundaryIngressPage,
    BoundaryIngressResponse,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryIngressId,
)
from app.boundary.persistence import (
    BoundaryEgressQuery,
    BoundaryIngressQuery,
    BoundaryPersistenceProtocol,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_boundary_repository

router = APIRouter(tags=["boundary"])

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


@router.get(
    "/ingress/{ingress_id}",
    response_model=BoundaryIngressResponse,
)
async def get_ingress(
    ingress_id: str,
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryIngressResponse:
    iid = _parse_uuid_or_404(ingress_id, kind="ingress")
    record = await repo.get_ingress(
        BoundaryIngressId(iid),
        expected_tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "ingress_not_found"}
        )
    return BoundaryIngressResponse.from_record(record)


@router.get(
    "/egress/{egress_id}",
    response_model=BoundaryEgressResponse,
)
async def get_egress(
    egress_id: str,
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryEgressResponse:
    eid = _parse_uuid_or_404(egress_id, kind="egress")
    record = await repo.get_egress(
        BoundaryEgressId(eid),
        expected_tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "egress_not_found"}
        )
    return BoundaryEgressResponse.from_record(record)


@router.get(
    "/ingress",
    response_model=BoundaryIngressPage,
)
async def list_ingress(
    source_type: str | None = Query(None),
    correlation_id: str | None = Query(None),
    request_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryIngressPage:
    from app.boundary.enums import BoundarySourceType

    source_enum: BoundarySourceType | None = None
    if source_type is not None:
        try:
            source_enum = BoundarySourceType(source_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_source_type", "reason": str(exc)},
            ) from exc
    query = BoundaryIngressQuery(
        source_type=source_enum,
        correlation_id=correlation_id,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )
    page = await repo.list_ingress(
        query, expected_tenant_id=expected_tenant_id
    )
    return BoundaryIngressPage(
        items=[BoundaryIngressResponse.from_record(r) for r in page.ingress],
        total=page.total,
    )


@router.get(
    "/egress",
    response_model=BoundaryEgressPage,
)
async def list_egress(
    source_type: str | None = Query(None),
    correlation_id: str | None = Query(None),
    request_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryEgressPage:
    from app.boundary.enums import BoundarySourceType

    source_enum: BoundarySourceType | None = None
    if source_type is not None:
        try:
            source_enum = BoundarySourceType(source_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_source_type", "reason": str(exc)},
            ) from exc
    query = BoundaryEgressQuery(
        source_type=source_enum,
        correlation_id=correlation_id,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )
    page = await repo.list_egress(
        query, expected_tenant_id=expected_tenant_id
    )
    return BoundaryEgressPage(
        items=[BoundaryEgressResponse.from_record(r) for r in page.egress],
        total=page.total,
    )


__all__ = ["router"]
