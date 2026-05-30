from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.persistence import InMemoryBoundaryPersistence
from app.core.config import get_settings
from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.governance.persistence import DecisionQuery, PostgresGovernanceRepository
from app.semantic import (
    SemanticCircuitEventRepository,
    SemanticCircuitState,
    TextFingerprinter,
)
from app.services.quarantine_service import (
    QuarantineService,
    SEMANTIC_QUARANTINE_FALSE_POSITIVE,
    SEMANTIC_QUARANTINE_FRAUD_CONFIRMED,
    SEMANTIC_QUARANTINE_PENDING,
    SemanticQuarantineAlreadyReviewedError,
    SemanticQuarantinePublisher,
    SemanticQuarantineRecord,
)
from app.services.ticket_ingress_service import (
    TicketIngressService,
    TicketIngressServiceResult,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant


_TENANT_ID = "test-pg-tenant"
_SAMPLE_CONTENT = "the charger stopped working after one week of use"


class _FakeCircuitBreaker:
    def __init__(
        self,
        state: SemanticCircuitState,
        cluster_size: int = 5,
    ) -> None:
        self.state = state
        self.cluster_size = cluster_size
        self.similarity_threshold = 0.7
        self.window_seconds = 300

    async def evaluate(
        self,
        *,
        tenant_id: str,
        channel: str,
        ticket_id: str,
        fingerprint: tuple[int, ...],
    ) -> tuple[SemanticCircuitState, int]:
        return self.state, self.cluster_size


class _FakePublisher(SemanticQuarantinePublisher):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish(
        self,
        *,
        quarantine_id: str,
        tenant_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        self.calls.append(
            {
                "quarantine_id": quarantine_id,
                "tenant_id": tenant_id,
                "payload": dict(payload),
            }
        )


class _ReingestRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(
        self,
        *,
        external_id: str,
        channel: str,
        raw_content: str,
        language_code: str,
        expected_tenant_id: str,
        semantic_quarantine_enabled: bool,
    ) -> object:
        self.calls.append(
            {
                "external_id": external_id,
                "channel": channel,
                "raw_content": raw_content,
                "language_code": language_code,
                "expected_tenant_id": expected_tenant_id,
                "semantic_quarantine_enabled": semantic_quarantine_enabled,
            }
        )
        return TicketIngressServiceResult(
            ingress_id="released-ingress",
            canonical_envelope_id="released-event",
        )


class _QuarantinedIngressService:
    async def process(
        self,
        *,
        external_id: str,
        channel: str,
        raw_content: str,
        language_code: str,
        expected_tenant_id: str,
    ) -> TicketIngressServiceResult:
        return TicketIngressServiceResult(
            ingress_id=None,
            canonical_envelope_id=None,
            quarantine_id="00000000-0000-0000-0000-00000000f003",
            status="quarantined",
        )


@requires_postgres
@pytest.mark.asyncio
async def test_tripped_circuit_routes_to_quarantine(
    pg_session: AsyncSession,
) -> None:
    publisher = _FakePublisher()
    quarantine = QuarantineService(pg_session, publisher=publisher)
    service = TicketIngressService(
        persistence=InMemoryBoundaryPersistence(),
        session=pg_session,
        circuit_breaker=cast(
            Any,
            _FakeCircuitBreaker(SemanticCircuitState.TRIPPED),
        ),
        circuit_event_repo=SemanticCircuitEventRepository(pg_session),
        quarantine_service=quarantine,
    )

    result = await service.process(
        external_id="scb3-tripped",
        channel="email",
        raw_content=_SAMPLE_CONTENT,
        language_code="en",
        expected_tenant_id=_TENANT_ID,
    )
    records = await quarantine.list_pending(
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    assert result.status == "quarantined"
    assert result.ingress_id is None
    assert result.canonical_envelope_id is None
    assert result.quarantine_id is not None
    assert [record.quarantine_id for record in records] == [result.quarantine_id]
    assert publisher.calls


@requires_postgres
@pytest.mark.asyncio
async def test_quarantine_emits_event(
    pg_session: AsyncSession,
) -> None:
    event_store = InMemoryOperationalEventPersistence()
    quarantine = QuarantineService(
        pg_session,
        publisher=_FakePublisher(),
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    record = await _create_pending_quarantine(quarantine)
    page = await event_store.list_events(
        OperationalEventQuery(
            operational_act=OperationalAct.SEMANTIC_QUARANTINE_CREATED,
            substrate=OperationalSubstrate.BOUNDARY,
        ),
        expected_tenant_id=_TENANT_ID,
    )

    assert page.total == 1
    event = page.events[0]
    assert event.metadata["_schema_version"] == "1"
    assert event.metadata["quarantine_id"] == record.quarantine_id
    assert event.metadata["tenant_id"] == _TENANT_ID
    assert event.metadata["channel"] == "email"
    assert event.metadata["cluster_size"] == 5


@requires_postgres
@pytest.mark.asyncio
async def test_normal_ticket_not_quarantined(
    pg_session: AsyncSession,
) -> None:
    publisher = _FakePublisher()
    quarantine = QuarantineService(pg_session, publisher=publisher)
    service = TicketIngressService(
        persistence=InMemoryBoundaryPersistence(),
        session=pg_session,
        circuit_breaker=cast(
            Any,
            _FakeCircuitBreaker(SemanticCircuitState.CLOSED, cluster_size=1),
        ),
        quarantine_service=quarantine,
    )

    result = await service.process(
        external_id="scb3-normal",
        channel="email",
        raw_content=_SAMPLE_CONTENT,
        language_code="en",
        expected_tenant_id=_TENANT_ID,
    )
    records = await quarantine.list_pending(
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    assert result.status == "received"
    assert result.ingress_id is not None
    assert result.canonical_envelope_id is not None
    assert result.quarantine_id is None
    assert records == []
    assert publisher.calls == []


@requires_postgres
@pytest.mark.asyncio
async def test_false_positive_triggers_re_ingestion(
    pg_session: AsyncSession,
) -> None:
    reingest = _ReingestRecorder()
    quarantine = QuarantineService(
        pg_session,
        publisher=_FakePublisher(),
        ticket_reingest=reingest,
    )
    record = await _create_pending_quarantine(quarantine)
    await pg_session.commit()

    released = await quarantine.release(
        quarantine_id=record.quarantine_id,
        verdict=SEMANTIC_QUARANTINE_FALSE_POSITIVE,
        reviewed_by="operator-1",
        note="known customer campaign",
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    assert released.status == SEMANTIC_QUARANTINE_FALSE_POSITIVE
    assert reingest.calls == [
        {
            "external_id": record.external_id,
            "channel": record.channel,
            "raw_content": _SAMPLE_CONTENT,
            "language_code": "en",
            "expected_tenant_id": _TENANT_ID,
            "semantic_quarantine_enabled": False,
        }
    ]


@requires_postgres
@pytest.mark.asyncio
async def test_fraud_confirmed_creates_deny_decision(
    pg_session: AsyncSession,
) -> None:
    reingest = _ReingestRecorder()
    quarantine = QuarantineService(
        pg_session,
        publisher=_FakePublisher(),
        ticket_reingest=reingest,
    )
    record = await _create_pending_quarantine(quarantine)
    await pg_session.commit()

    released = await quarantine.release(
        quarantine_id=record.quarantine_id,
        verdict=SEMANTIC_QUARANTINE_FRAUD_CONFIRMED,
        reviewed_by="operator-1",
        note="confirmed coordinated abuse",
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )
    decisions = await PostgresGovernanceRepository(pg_session).query_decisions(
        DecisionQuery(
            tenant_id=_TENANT_ID,
            subject_kind="fraud_determination",
            final_decision=Decision.DENY.value,
            limit=10,
        )
    )

    assert released.status == SEMANTIC_QUARANTINE_FRAUD_CONFIRMED
    assert reingest.calls == []
    assert len(decisions.items) == 1
    assert decisions.items[0].reason == "fraud_determination"
    assert decisions.items[0].metadata["quarantine_id"] == record.quarantine_id


@requires_postgres
@pytest.mark.asyncio
async def test_fraud_confirmed_not_republished(
    pg_session: AsyncSession,
) -> None:
    publisher = _FakePublisher()
    reingest = _ReingestRecorder()
    quarantine = QuarantineService(
        pg_session,
        publisher=publisher,
        ticket_reingest=reingest,
    )
    record = await _create_pending_quarantine(quarantine)
    await pg_session.commit()
    publisher.calls.clear()

    await quarantine.release(
        quarantine_id=record.quarantine_id,
        verdict=SEMANTIC_QUARANTINE_FRAUD_CONFIRMED,
        reviewed_by="operator-1",
        note=None,
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    assert publisher.calls == []
    assert reingest.calls == []


@requires_postgres
@pytest.mark.asyncio
async def test_release_pending_only(
    pg_session: AsyncSession,
) -> None:
    quarantine = QuarantineService(
        pg_session,
        publisher=_FakePublisher(),
        ticket_reingest=_ReingestRecorder(),
    )
    record = await _create_pending_quarantine(quarantine)
    await pg_session.commit()
    await quarantine.release(
        quarantine_id=record.quarantine_id,
        verdict=SEMANTIC_QUARANTINE_FALSE_POSITIVE,
        reviewed_by="operator-1",
        note=None,
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    with pytest.raises(SemanticQuarantineAlreadyReviewedError):
        await quarantine.release(
            quarantine_id=record.quarantine_id,
            verdict=SEMANTIC_QUARANTINE_FRAUD_CONFIRMED,
            reviewed_by="operator-2",
            note=None,
            tenant_id=_TENANT_ID,
            expected_tenant_id=_TENANT_ID,
        )


@requires_postgres
@pytest.mark.asyncio
async def test_quarantine_tenant_isolation(
    pg_session: AsyncSession,
) -> None:
    await set_pg_rls_tenant(pg_session, "tenant-a")
    quarantine = QuarantineService(pg_session, publisher=_FakePublisher())
    await _create_pending_quarantine(
        quarantine,
        tenant_id="tenant-a",
        external_id="tenant-a-ticket",
    )
    await pg_session.commit()
    await set_pg_rls_tenant(pg_session, "tenant-b")

    tenant_b_records = await quarantine.list_pending(
        tenant_id="tenant-b",
        expected_tenant_id="tenant-b",
    )

    assert tenant_b_records == []


@pytest.mark.asyncio
async def test_202_returned_for_quarantined_ticket() -> None:
    from app.dependencies.services import get_ticket_ingress_service
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_ticket_ingress_service] = (
        lambda: _QuarantinedIngressService()
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/boundary/translation/ingress",
            json={
                "external_id": "quarantined-ticket",
                "channel": "email",
                "raw_content": _SAMPLE_CONTENT,
                "language_code": "en",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "quarantined"
    assert response.json()["ingress_id"] is None
    assert response.json()["quarantine_id"] == (
        "00000000-0000-0000-0000-00000000f003"
    )


async def _create_pending_quarantine(
    quarantine: QuarantineService,
    *,
    tenant_id: str = _TENANT_ID,
    external_id: str = "scb3-pending",
) -> SemanticQuarantineRecord:
    quarantine_id = await quarantine.quarantine_ticket(
        tenant_id=tenant_id,
        channel="email",
        external_id=external_id,
        ticket_payload={
            "content": _SAMPLE_CONTENT,
            "channel": "email",
            "tenant_id": tenant_id,
            "external_id": external_id,
            "language_code": "en",
            "metadata": {},
        },
        fingerprint=list(TextFingerprinter().fingerprint(_SAMPLE_CONTENT)),
        cluster_size=5,
        similarity_threshold=0.7,
        expected_tenant_id=tenant_id,
    )
    record = await quarantine.list_records(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
        status=SEMANTIC_QUARANTINE_PENDING,
        limit=1,
    )
    assert record[0].quarantine_id == quarantine_id
    return record[0]
