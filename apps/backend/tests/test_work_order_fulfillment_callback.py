"""Phase 2.3.x-c inbound fulfillment callback break-controls."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.enums import BoundaryMessageType
from app.boundary.identity import BoundaryIngressId
from app.boundary.persistence import (
    BoundaryIngressRecord,
    PostgresBoundaryPersistence,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from app.services.work_order_fulfillment_events import (
    fulfillment_signal_from_ingress_record,
)
from app.tenant.db.models import TenantRow
from app.work_orders.enums import WorkOrderState
from app.work_orders.fulfillment import (
    WorkOrderFulfillmentConsumptionResult,
    WorkOrderFulfillmentConsumer,
    WorkOrderFulfillmentOutcome,
)
from app.work_orders.identity import WorkOrderId, derive_work_order_id
from app.work_orders.persistence import (
    PostgresWorkOrderRepository,
    WorkOrderRecord,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [pytest.mark.asyncio, requires_postgres]

_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
_CONFIG_SHA = "c" * 64
_SOURCE_APPROVAL_ID = "approval-work-order-fulfillment-config"
_APP_DIR = Path("apps/backend/app")


@pytest_asyncio.fixture
async def fulfillment_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


@requires_postgres
async def test_2_3_x_c_1_callback_advances_awaiting_to_terminal_states(
    pg_session: AsyncSession,
    fulfillment_client: httpx.AsyncClient,
) -> None:
    fulfilled = await _seed_awaiting_work_order(
        pg_session,
        tenant_id="tenant-fulfillment-c1-fulfilled",
        provider_work_order_id="provider-c1-fulfilled",
        seed="c1-fulfilled",
    )
    failed = await _seed_awaiting_work_order(
        pg_session,
        tenant_id="tenant-fulfillment-c1-failed",
        provider_work_order_id="provider-c1-failed",
        seed="c1-failed",
    )

    fulfilled_record = await _post_and_load_record(
        pg_session,
        fulfillment_client,
        tenant_id="tenant-fulfillment-c1-fulfilled",
        provider_work_order_id="provider-c1-fulfilled",
        status="fulfilled",
        callback_id="callback-c1-fulfilled",
    )
    failed_record = await _post_and_load_record(
        pg_session,
        fulfillment_client,
        tenant_id="tenant-fulfillment-c1-failed",
        provider_work_order_id="provider-c1-failed",
        status="failed",
        callback_id="callback-c1-failed",
        provider_error="repair could not be completed",
    )

    fulfilled_result = await _consume_record(
        pg_session,
        fulfilled_record,
        expected_tenant_id="tenant-fulfillment-c1-fulfilled",
    )
    failed_result = await _consume_record(
        pg_session,
        failed_record,
        expected_tenant_id="tenant-fulfillment-c1-failed",
    )

    assert fulfilled_result.outcome is WorkOrderFulfillmentOutcome.APPLIED
    assert fulfilled_result.work_order_id == fulfilled.work_order_id
    assert fulfilled_result.to_state is WorkOrderState.FULFILLED
    assert failed_result.outcome is WorkOrderFulfillmentOutcome.APPLIED
    assert failed_result.work_order_id == failed.work_order_id
    assert failed_result.to_state is WorkOrderState.FAILED


@requires_postgres
async def test_2_3_x_c_2_provider_correlation_is_tenant_scoped(
    pg_session: AsyncSession,
    fulfillment_client: httpx.AsyncClient,
) -> None:
    provider_id = "provider-collides-across-tenants"
    tenant_a = "tenant-fulfillment-c2-a"
    tenant_b = "tenant-fulfillment-c2-b"
    tenant_a_order = await _seed_awaiting_work_order(
        pg_session,
        tenant_id=tenant_a,
        provider_work_order_id=provider_id,
        seed="c2-a",
    )
    tenant_b_order = await _seed_awaiting_work_order(
        pg_session,
        tenant_id=tenant_b,
        provider_work_order_id=provider_id,
        seed="c2-b",
    )

    record = await _post_and_load_record(
        pg_session,
        fulfillment_client,
        tenant_id=tenant_a,
        provider_work_order_id=provider_id,
        status="fulfilled",
        callback_id="callback-c2-a",
    )
    result = await _consume_record(
        pg_session,
        record,
        expected_tenant_id=tenant_a,
    )

    assert result.outcome is WorkOrderFulfillmentOutcome.APPLIED
    assert result.work_order_id == tenant_a_order.work_order_id
    assert (
        await _load_work_order(
            pg_session,
            tenant_id=tenant_a,
            work_order_id=tenant_a_order.work_order_id,
        )
    ).state is WorkOrderState.FULFILLED
    assert (
        await _load_work_order(
            pg_session,
            tenant_id=tenant_b,
            work_order_id=tenant_b_order.work_order_id,
        )
    ).state is WorkOrderState.AWAITING_FULFILLMENT


@requires_postgres
async def test_2_3_x_c_3_duplicate_callback_is_noop_after_first_transition(
    pg_session: AsyncSession,
    fulfillment_client: httpx.AsyncClient,
) -> None:
    tenant_id = "tenant-fulfillment-c3"
    provider_id = "provider-c3-duplicate"
    seeded = await _seed_awaiting_work_order(
        pg_session,
        tenant_id=tenant_id,
        provider_work_order_id=provider_id,
        seed="c3",
    )

    first_record = await _post_and_load_record(
        pg_session,
        fulfillment_client,
        tenant_id=tenant_id,
        provider_work_order_id=provider_id,
        status="fulfilled",
        callback_id="callback-c3-duplicate",
    )
    second_record = await _post_and_load_record(
        pg_session,
        fulfillment_client,
        tenant_id=tenant_id,
        provider_work_order_id=provider_id,
        status="fulfilled",
        callback_id="callback-c3-duplicate",
    )
    first = await _consume_record(
        pg_session,
        first_record,
        expected_tenant_id=tenant_id,
    )
    second = await _consume_record(
        pg_session,
        second_record,
        expected_tenant_id=tenant_id,
    )
    loaded = await _load_work_order(
        pg_session,
        tenant_id=tenant_id,
        work_order_id=seeded.work_order_id,
    )

    assert first.outcome is WorkOrderFulfillmentOutcome.APPLIED
    assert second.outcome is WorkOrderFulfillmentOutcome.DUPLICATE
    assert first_record.ingress_id == second_record.ingress_id
    assert loaded.state is WorkOrderState.FULFILLED
    assert [
        (item["from"], item["to"])
        for item in loaded.transition_history
    ] == [
        ("created", "dispatched"),
        ("dispatched", "awaiting_fulfillment"),
        ("awaiting_fulfillment", "fulfilled"),
    ]


@requires_postgres
async def test_2_3_x_c_4_ingress_records_only_consumer_mutates_work_order(
    pg_session: AsyncSession,
    fulfillment_client: httpx.AsyncClient,
) -> None:
    tenant_id = "tenant-fulfillment-c4"
    provider_id = "provider-c4-record-only"
    seeded = await _seed_awaiting_work_order(
        pg_session,
        tenant_id=tenant_id,
        provider_work_order_id=provider_id,
        seed="c4",
    )

    record = await _post_and_load_record(
        pg_session,
        fulfillment_client,
        tenant_id=tenant_id,
        provider_work_order_id=provider_id,
        status="fulfilled",
        callback_id="callback-c4-record-only",
    )
    before_consumer = await _load_work_order(
        pg_session,
        tenant_id=tenant_id,
        work_order_id=seeded.work_order_id,
    )

    assert record.message_type is BoundaryMessageType.STATUS_UPDATE
    assert before_consumer.state is WorkOrderState.AWAITING_FULFILLMENT
    assert "app.work_orders" not in Path(
        "apps/backend/app/api/v1/routers/boundary.py"
    ).read_text(encoding="utf-8")
    assert "app.work_orders" not in Path(
        "apps/backend/app/services/work_order_fulfillment_receipt_service.py"
    ).read_text(encoding="utf-8")

    consumed = await _consume_record(
        pg_session,
        record,
        expected_tenant_id=tenant_id,
    )
    after_consumer = await _load_work_order(
        pg_session,
        tenant_id=tenant_id,
        work_order_id=seeded.work_order_id,
    )

    assert consumed.outcome is WorkOrderFulfillmentOutcome.APPLIED
    assert after_consumer.state is WorkOrderState.FULFILLED


@requires_postgres
async def test_2_3_x_c_5_no_internal_auto_fulfillment_without_tenant_report(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-fulfillment-c5"
    seeded = await _seed_awaiting_work_order(
        pg_session,
        tenant_id=tenant_id,
        provider_work_order_id="provider-c5-no-report",
        seed="c5",
    )

    loaded = await _load_work_order(
        pg_session,
        tenant_id=tenant_id,
        work_order_id=seeded.work_order_id,
    )

    assert loaded.state is WorkOrderState.AWAITING_FULFILLMENT
    assert not _internal_fulfillment_transition_violations()


async def _post_and_load_record(
    session: AsyncSession,
    client: httpx.AsyncClient,
    *,
    tenant_id: str,
    provider_work_order_id: str,
    status: str,
    callback_id: str,
    provider_error: str | None = None,
) -> BoundaryIngressRecord:
    response = await client.post(
        "/api/v1/boundary/work-orders/fulfillment",
        headers=_headers(tenant_id),
        json={
            "provider_work_order_id": provider_work_order_id,
            "status": status,
            "callback_id": callback_id,
            "provider_error": provider_error,
            "reported_at": _NOW.isoformat(),
            "metadata": {"provider": "tenant-system"},
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    repo = PostgresBoundaryPersistence(session)
    record = await repo.get_ingress(
        BoundaryIngressId(uuid.UUID(body["ingress_id"])),
        expected_tenant_id=tenant_id,
    )
    assert record is not None
    return record


async def _consume_record(
    session: AsyncSession,
    record: BoundaryIngressRecord,
    *,
    expected_tenant_id: str,
) -> WorkOrderFulfillmentConsumptionResult:
    signal = fulfillment_signal_from_ingress_record(
        record,
        expected_tenant_id=expected_tenant_id,
    )
    assert signal is not None
    return await WorkOrderFulfillmentConsumer(
        repository=PostgresWorkOrderRepository(session),
        now=_NOW,
    ).consume(signal, expected_tenant_id=expected_tenant_id)


async def _seed_awaiting_work_order(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider_work_order_id: str,
    seed: str,
) -> WorkOrderRecord:
    await _seed_tenant(session, tenant_id)
    await set_pg_rls_tenant(session, tenant_id)
    repo = PostgresWorkOrderRepository(session)
    created = await repo.create_work_order(
        _work_order_record(tenant_id, seed=seed),
        expected_tenant_id=tenant_id,
    )
    dispatched = await repo.transition_work_order(
        created.work_order_id,
        to_state=WorkOrderState.DISPATCHED,
        transitioned_at=_NOW,
        expected_tenant_id=tenant_id,
        provider_work_order_id=provider_work_order_id,
        provider_status="accepted",
        metadata={"phase": "dispatch_accepted"},
    )
    return await repo.transition_work_order(
        dispatched.work_order_id,
        to_state=WorkOrderState.AWAITING_FULFILLMENT,
        transitioned_at=_NOW,
        expected_tenant_id=tenant_id,
        provider_work_order_id=provider_work_order_id,
        provider_status="accepted",
        metadata={"phase": "awaiting_tenant_fulfillment"},
    )


async def _load_work_order(
    session: AsyncSession,
    *,
    tenant_id: str,
    work_order_id: WorkOrderId,
) -> WorkOrderRecord:
    loaded = await PostgresWorkOrderRepository(session).get_work_order(
        work_order_id,
        expected_tenant_id=tenant_id,
    )
    assert loaded is not None
    return loaded


async def _seed_tenant(session: AsyncSession, tenant_id: str) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()


def _work_order_record(tenant_id: str, *, seed: str) -> WorkOrderRecord:
    action_type = "repair.dispatch"
    idempotency_key = f"fulfillment:{seed}"
    return WorkOrderRecord(
        work_order_id=derive_work_order_id(
            tenant_id=tenant_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
        ),
        tenant_id=tenant_id,
        action_type=action_type,
        tool_name="repair.dispatch",
        connector_type="generic_rest_work_order",
        connector_config_version=1,
        connector_config_content_sha256=_CONFIG_SHA,
        connector_config_source_approval_id=_SOURCE_APPROVAL_ID,
        idempotency_key=idempotency_key,
        target_resource=f"repair:{seed}",
        metadata={"seed": seed},
    )


def _headers(tenant_id: str) -> dict[str, str]:
    return {"X-Tenant-ID": tenant_id, "X-Principal-ID": "principal-test"}


def _internal_fulfillment_transition_violations() -> list[str]:
    allowed = {
        _APP_DIR / "work_orders" / "enums.py",
        _APP_DIR / "work_orders" / "fulfillment.py",
        _APP_DIR / "work_orders" / "state_machine.py",
    }
    violations: list[str] = []
    for pyfile in sorted(_APP_DIR.rglob("*.py")):
        if pyfile in allowed:
            continue
        source = pyfile.read_text(encoding="utf-8")
        if "WorkOrderState.FULFILLED" in source:
            violations.append(str(pyfile))
    return violations
