"""Shopify SKU extraction and defect-cluster enrichment tests."""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.boundary.shopify.client as shopify_client_module
from app.boundary.shopify import (
    DeterministicStubShopifyClient,
    ShopifyOrder,
)
from app.execution import ExecutionState
from app.execution.db.models import ExecutionRow
from app.execution.enums import ExecutionKind
from app.runtime.db.models import DefectClusterRow
from app.services.shopify_enrichment_service import ShopifyEnrichmentService
from app.services.sku_extraction_service import SKUExtractionService
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres, set_pg_rls_tenant

_NOW = datetime(2026, 5, 30, 13, tzinfo=timezone.utc)
_NAMESPACE = uuid.UUID("4a0f37b5-2e11-5b77-a8b6-ea9501e27d43")

pytestmark = [pytest.mark.asyncio, requires_postgres]


async def test_sku_extracted_from_action_payloads(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-shopify-sku"
    execution_id, session_id = await _seed_execution(
        pg_session,
        tenant_id=tenant_id,
        suffix="with-sku",
    )
    await _seed_action_approval(
        pg_session,
        tenant_id=tenant_id,
        execution_id=execution_id,
        session_id=session_id,
        payload={"product_sku": "A3219"},
    )
    service = SKUExtractionService(session=pg_session)

    sku = await service.extract_sku_for_cluster(
        execution_ids=(str(execution_id),),
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert sku == "A3219"


async def test_sku_extraction_returns_none_when_absent(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-shopify-no-sku"
    execution_id, _session_id = await _seed_execution(
        pg_session,
        tenant_id=tenant_id,
        suffix="without-sku",
    )
    service = SKUExtractionService(session=pg_session)

    sku = await service.extract_sku_for_cluster(
        execution_ids=(str(execution_id),),
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert sku is None


async def test_stub_client_returns_fixture_data() -> None:
    client = DeterministicStubShopifyClient()

    product = await client.get_product_by_sku("A3219")
    orders = await client.get_recent_orders_by_sku("A3219")

    assert product.variants[0].sku == "A3219"
    assert orders[0].line_item_skus == ("A3219",)


async def test_enrichment_stored_in_cluster_metadata(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-shopify-enrich"
    cluster = await _seed_cluster(
        pg_session,
        tenant_id=tenant_id,
        sku_hint="A3219",
    )
    service = ShopifyEnrichmentService(
        session=pg_session,
        client=DeterministicStubShopifyClient(),
        now=lambda: _NOW,
    )

    enriched = await service.enrich_cluster(
        cluster_id=str(cluster.cluster_id),
        sku_hint="A3219",
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert enriched is True
    enrichment = cluster.metadata_json["shopify_enrichment"]
    assert enrichment["sku"] == "A3219"
    assert enrichment["product"]["variants"][0]["sku"] == "A3219"
    assert enrichment["recent_orders"][0]["line_item_skus"] == ["A3219"]


async def test_enrichment_fail_open_on_api_error(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-shopify-fail-open"
    cluster = await _seed_cluster(
        pg_session,
        tenant_id=tenant_id,
        sku_hint="A3219",
    )
    service = ShopifyEnrichmentService(
        session=pg_session,
        client=_FailingShopifyClient(),
    )

    enriched = await service.enrich_cluster(
        cluster_id=str(cluster.cluster_id),
        sku_hint="A3219",
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert enriched is False
    assert "shopify_enrichment" not in cluster.metadata_json


async def test_enrichment_uses_stub_when_no_credentials(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-shopify-stub"
    cluster = await _seed_cluster(
        pg_session,
        tenant_id=tenant_id,
        sku_hint="A3219",
    )
    service = ShopifyEnrichmentService(
        session=pg_session,
        now=lambda: _NOW,
    )

    enriched = await service.enrich_cluster(
        cluster_id=str(cluster.cluster_id),
        sku_hint="A3219",
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert enriched is True
    enrichment = cluster.metadata_json["shopify_enrichment"]
    assert enrichment["enrichment_source"] == "stub"
    assert enrichment["sku"] == "A3219"


async def test_shopify_client_no_governance_import() -> None:
    source = inspect.getsource(shopify_client_module)

    assert "governance" not in source
    assert ".post(" not in source


async def _seed_execution(
    session: AsyncSession,
    *,
    tenant_id: str,
    suffix: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    await _ensure_tenant(session, tenant_id)
    execution_id = uuid.uuid5(_NAMESPACE, f"execution|{tenant_id}|{suffix}")
    session_id = uuid.uuid5(_NAMESPACE, f"session|{tenant_id}|{suffix}")
    session.add(
        ExecutionRow(
            execution_id=execution_id,
            kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
            dispatch_id=f"dispatch-{execution_id}",
            session_id=str(session_id),
            tenant_id=tenant_id,
            state=ExecutionState.COMPLETED.value,
            attempt_count=1,
            requested_at=_NOW - timedelta(minutes=5),
            completed_at=_NOW - timedelta(minutes=4),
            diagnostic_category="charging_issue",
            diagnostic_confidence=0.9,
            result={
                "diagnostic_category": "charging_issue",
                "diagnostic_confidence": 0.9,
                "diagnostic_summary": "Charging failure summary.",
            },
            metadata_json={},
        )
    )
    await session.flush()
    return execution_id, session_id


async def _seed_action_approval(
    session: AsyncSession,
    *,
    tenant_id: str,
    execution_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: dict[str, object],
) -> None:
    approval_id = uuid.uuid5(
        _NAMESPACE,
        f"approval|{tenant_id}|{execution_id}",
    )
    idempotency_key = uuid.uuid5(
        _NAMESPACE,
        f"idempotency|{tenant_id}|{execution_id}",
    )
    await session.execute(
        text(
            """
            INSERT INTO public.action_approval_records (
                approval_id,
                tenant_id,
                session_id,
                execution_id,
                tool_name,
                idempotency_key,
                payload_json,
                governance_decision_id,
                status,
                requested_at,
                metadata
            )
            VALUES (
                CAST(:approval_id AS uuid),
                :tenant_id,
                CAST(:session_id AS uuid),
                CAST(:execution_id AS uuid),
                :tool_name,
                CAST(:idempotency_key AS uuid),
                CAST(:payload_json AS jsonb),
                NULL,
                'pending',
                :requested_at,
                '{}'::jsonb
            )
            """
        ),
        {
            "approval_id": str(approval_id),
            "tenant_id": tenant_id,
            "session_id": str(session_id),
            "execution_id": str(execution_id),
            "tool_name": "create_warranty_claim",
            "idempotency_key": str(idempotency_key),
            "payload_json": json.dumps(payload),
            "requested_at": _NOW,
        },
    )
    await session.flush()


async def _seed_cluster(
    session: AsyncSession,
    *,
    tenant_id: str,
    sku_hint: str | None,
) -> DefectClusterRow:
    await _ensure_tenant(session, tenant_id)
    cluster = DefectClusterRow(
        cluster_id=uuid.uuid5(_NAMESPACE, f"cluster|{tenant_id}"),
        tenant_id=tenant_id,
        category="charging_issue",
        execution_count=5,
        window_hours=24,
        window_start=_NOW - timedelta(hours=1),
        window_end=_NOW,
        threshold_used=5,
        sku_hint=sku_hint,
        failure_step_hint=None,
        status="detected",
        metadata_json={},
    )
    session.add(cluster)
    await session.flush()
    return cluster


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()


class _FailingShopifyClient:
    async def get_product_by_sku(self, sku: str) -> None:
        del sku
        raise RuntimeError("shopify unavailable")

    async def get_recent_orders_by_sku(
        self,
        sku: str,
        limit: int = 10,
    ) -> list[ShopifyOrder]:
        del sku, limit
        raise RuntimeError("shopify unavailable")
