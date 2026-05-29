"""Defect-cluster scheduled scan worker tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_owner_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.runtime.defect_cluster_runtime import DefectClusterDetectionRuntime
from app.tenant.db.models import TenantRow
from app.queues import QUEUE_SUPERVISOR
from app.workers.celery_app import celery_app

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="scan_for_defect_clusters",
    queue=QUEUE_SUPERVISOR,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=60,
)
def scan_for_defect_clusters(_self: Any) -> dict[str, object]:
    """PRIVILEGED_PATH: scan all tenant diagnostic executions."""

    return _run_async(
        scan_for_defect_clusters_runtime(),
        tenant_id="maintenance",
    )


async def scan_for_defect_clusters_runtime(
    *,
    tenant_ids: tuple[str, ...] | None = None,
    session: AsyncSession | None = None,
) -> dict[str, object]:
    settings = get_settings()
    if session is not None:
        return await _scan_for_defect_clusters_with_session(
            session=session,
            tenant_ids=tenant_ids,
            window_hours=settings.DEFECT_CLUSTER_WINDOW_HOURS,
            threshold=settings.DEFECT_CLUSTER_THRESHOLD,
        )

    # PRIVILEGED_PATH: enumerate tenant ids under owner privileges, then
    # reinstate tenant context before every scoped scan/write.
    session_factory = get_owner_session_factory()
    async with session_factory() as owned_session:
        return await _scan_for_defect_clusters_with_session(
            session=owned_session,
            tenant_ids=tenant_ids,
            window_hours=settings.DEFECT_CLUSTER_WINDOW_HOURS,
            threshold=settings.DEFECT_CLUSTER_THRESHOLD,
        )


async def _scan_for_defect_clusters_with_session(
    *,
    session: AsyncSession,
    tenant_ids: tuple[str, ...] | None,
    window_hours: int,
    threshold: int,
) -> dict[str, object]:
    tenants = (
        tenant_ids
        if tenant_ids is not None
        else await _tenant_ids_for_defect_scan(session)
    )
    if not tenants and get_current_tenant():
        tenants = (str(get_current_tenant()),)

    runtime = DefectClusterDetectionRuntime(session=session)
    detected: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    for tenant_id in tenants:
        set_current_tenant(tenant_id)
        await _set_db_tenant_context(session, tenant_id)
        try:
            candidates = await runtime.scan_tenant(
                tenant_id=tenant_id,
                expected_tenant_id=tenant_id,
                window_hours=window_hours,
                threshold=threshold,
            )
            for candidate in candidates:
                cluster_id = await runtime.emit_cluster_event(
                    candidate=candidate,
                    expected_tenant_id=tenant_id,
                )
                detected.append(
                    {
                        "tenant_id": tenant_id,
                        "category": candidate.category,
                        "cluster_id": cluster_id,
                        "execution_count": candidate.execution_count,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - fail open per tenant.
            failed.append(
                {
                    "tenant_id": tenant_id,
                    "reason": exc.__class__.__name__,
                }
            )
            logger.exception(
                "defect_cluster_scan_tenant_failed",
                extra={"tenant_id": tenant_id},
            )
    await session.commit()
    set_current_tenant(None)
    return {
        "status": "completed",
        "tenants_scanned": len(tenants),
        "clusters_detected": len(detected),
        "clusters": detected,
        "failed": failed,
    }


async def _tenant_ids_for_defect_scan(session: AsyncSession) -> tuple[str, ...]:
    rows = (await session.execute(select(TenantRow.tenant_id))).scalars().all()
    return tuple(str(row) for row in rows)


async def _set_db_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": tenant_id},
    )


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            set_current_tenant(None)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            set_current_tenant(None)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("defect cluster scan coroutine returned no result")
    return results[0]


__all__ = [
    "scan_for_defect_clusters",
    "scan_for_defect_clusters_runtime",
]
