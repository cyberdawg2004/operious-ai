"""Defect-cluster scheduled scan worker tasks."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from collections.abc import Coroutine
from threading import Thread
from typing import Any, Protocol, TypeVar, cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.defect_report_agent import (
    DefectReportSynthesisAgent,
    DeterministicDefectReportLLMClient,
    derive_defect_report_id,
)
from app.cognition.llm import AnthropicMessagesClient, DiagnosticLLMClient
from app.core.config import get_settings
from app.db.session import get_owner_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.runtime.defect_cluster_runtime import DefectClusterDetectionRuntime
from app.runtime.db.models import DefectClusterRow, DefectReportRow
from app.services.shopify_enrichment_service import ShopifyEnrichmentService
from app.services.sku_extraction_service import SKUExtractionService
from app.tenant.db.models import TenantRow
from app.queues import QUEUE_SUPERVISOR
from app.workers.celery_app import celery_app
from app.workers.outbound_tasks import dispatch_defect_report

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


class DefectReportSynthesisProtocol(Protocol):
    async def synthesize(
        self,
        *,
        cluster: DefectClusterRow,
        expected_tenant_id: str,
    ) -> str: ...


class SKUExtractionProtocol(Protocol):
    async def extract_sku_for_cluster(
        self,
        *,
        execution_ids: tuple[str, ...],
        tenant_id: str,
        expected_tenant_id: str,
    ) -> str | None: ...

    async def update_cluster_sku_hint(
        self,
        *,
        cluster_id: str,
        sku: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> bool: ...


class ShopifyEnrichmentProtocol(Protocol):
    async def enrich_cluster(
        self,
        *,
        cluster_id: str,
        sku_hint: str | None,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> bool: ...


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
    synthesis_agent: DefectReportSynthesisProtocol | None = None,
    sku_extraction_service: SKUExtractionProtocol | None = None,
    shopify_enrichment_service: ShopifyEnrichmentProtocol | None = None,
) -> dict[str, object]:
    settings = get_settings()
    if session is not None:
        return await _scan_for_defect_clusters_with_session(
            session=session,
            tenant_ids=tenant_ids,
            window_hours=settings.DEFECT_CLUSTER_WINDOW_HOURS,
            threshold=settings.DEFECT_CLUSTER_THRESHOLD,
            synthesis_agent=synthesis_agent,
            sku_extraction_service=sku_extraction_service,
            shopify_enrichment_service=shopify_enrichment_service,
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
            synthesis_agent=synthesis_agent,
            sku_extraction_service=sku_extraction_service,
            shopify_enrichment_service=shopify_enrichment_service,
        )


async def _scan_for_defect_clusters_with_session(
    *,
    session: AsyncSession,
    tenant_ids: tuple[str, ...] | None,
    window_hours: int,
    threshold: int,
    synthesis_agent: DefectReportSynthesisProtocol | None,
    sku_extraction_service: SKUExtractionProtocol | None,
    shopify_enrichment_service: ShopifyEnrichmentProtocol | None,
) -> dict[str, object]:
    tenants = (
        tenant_ids
        if tenant_ids is not None
        else await _tenant_ids_for_defect_scan(session)
    )
    if not tenants and get_current_tenant():
        tenants = (str(get_current_tenant()),)

    runtime = DefectClusterDetectionRuntime(session=session)
    synthesis = synthesis_agent or _defect_report_synthesis_agent(session)
    sku_extractor = sku_extraction_service or SKUExtractionService(session=session)
    shopify_enrichment = (
        shopify_enrichment_service
        or ShopifyEnrichmentService(session=session)
    )
    detected: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    enrichment_failed: list[dict[str, object]] = []
    synthesis_failed: list[dict[str, object]] = []
    dispatch_jobs: list[tuple[str, str]] = []
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
                report_id: str | None = None
                cluster = await session.get(
                    DefectClusterRow,
                    uuid.UUID(cluster_id),
                )
                if cluster is not None and cluster.status != "reported":
                    try:
                        sku = await sku_extractor.extract_sku_for_cluster(
                            execution_ids=candidate.execution_ids,
                            tenant_id=tenant_id,
                            expected_tenant_id=tenant_id,
                        )
                        if sku is not None:
                            await sku_extractor.update_cluster_sku_hint(
                                cluster_id=cluster_id,
                                sku=sku,
                                tenant_id=tenant_id,
                                expected_tenant_id=tenant_id,
                            )
                            cluster.sku_hint = sku
                            await shopify_enrichment.enrich_cluster(
                                cluster_id=cluster_id,
                                sku_hint=sku,
                                tenant_id=tenant_id,
                                expected_tenant_id=tenant_id,
                            )
                    except Exception as exc:  # noqa: BLE001 - enrichment is optional.
                        enrichment_failed.append(
                            {
                                "tenant_id": tenant_id,
                                "cluster_id": cluster_id,
                                "reason": exc.__class__.__name__,
                            }
                        )
                        logger.warning(
                            "defect_cluster_shopify_enrichment_failed",
                            extra={
                                "tenant_id": tenant_id,
                                "cluster_id": cluster_id,
                                "error_class": exc.__class__.__name__,
                            },
                        )
                    try:
                        report_id = await synthesis.synthesize(
                            cluster=cluster,
                            expected_tenant_id=tenant_id,
                        )
                    except Exception as exc:  # noqa: BLE001 - retry next beat.
                        synthesis_failed.append(
                            {
                                "tenant_id": tenant_id,
                                "cluster_id": cluster_id,
                                "reason": exc.__class__.__name__,
                            }
                        )
                        logger.exception(
                            "defect_report_synthesis_failed",
                            extra={
                                "tenant_id": tenant_id,
                                "cluster_id": cluster_id,
                            },
                        )
                if cluster is not None and cluster.status == "reported":
                    report_id = report_id or str(
                        derive_defect_report_id(cluster.cluster_id)
                    )
                    report = await session.get(
                        DefectReportRow,
                        uuid.UUID(report_id),
                    )
                    if (
                        report is not None
                        and report.governance_status == "allowed"
                        and report.dispatched_at is None
                    ):
                        dispatch_jobs.append((report_id, tenant_id))
                detected.append(
                    {
                        "tenant_id": tenant_id,
                        "category": candidate.category,
                        "cluster_id": cluster_id,
                        "execution_count": candidate.execution_count,
                        "report_id": report_id,
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
    dispatch_enqueued = 0
    for report_id, tenant_id in dispatch_jobs:
        cast(Any, dispatch_defect_report).delay(
            report_id=report_id,
            tenant_id=tenant_id,
            attempt_number=1,
        )
        dispatch_enqueued += 1
    set_current_tenant(None)
    return {
        "status": "completed",
        "tenants_scanned": len(tenants),
        "clusters_detected": len(detected),
        "clusters": detected,
        "failed": failed,
        "enrichment_failed": enrichment_failed,
        "synthesis_failed": synthesis_failed,
        "dispatch_enqueued": dispatch_enqueued,
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


def _defect_report_synthesis_agent(
    session: AsyncSession,
) -> DefectReportSynthesisAgent:
    return DefectReportSynthesisAgent(
        session=session,
        llm_client=_defect_report_llm_client(),
    )


def _defect_report_llm_client() -> DiagnosticLLMClient:
    settings = get_settings()
    if _running_under_pytest() or not settings.ANTHROPIC_API_KEY.strip():
        return DeterministicDefectReportLLMClient()
    return AnthropicMessagesClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model=settings.ANTHROPIC_DEFAULT_MODEL,
        base_url=settings.ANTHROPIC_BASE_URL,
        anthropic_version=settings.ANTHROPIC_VERSION,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
    )


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


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
