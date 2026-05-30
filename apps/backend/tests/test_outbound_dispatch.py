"""Outbound defect-report dispatch tests."""

from __future__ import annotations

import inspect
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.boundary.outbound.adapter as adapter_module
from app.boundary.outbound import (
    OutboundWebhookRequest,
    OutboundWebhookResponse,
    format_jira_payload,
    format_linear_payload,
)
from app.runtime.db.models import (
    DefectClusterRow,
    DefectReportRow,
    OutboundDispatchRow,
)
from app.services.outbound_dispatch_service import OutboundDispatchService
from app.tenant.db.models import TenantRow
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.identity import derive_channel_configuration_id
from app.tenant.persistence import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
    TenantChannelConfigurationRecord,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant

_NOW = datetime(2026, 5, 30, 12, tzinfo=timezone.utc)

pytestmark = [pytest.mark.asyncio, requires_postgres]


async def test_jira_payload_format() -> None:
    payload = format_jira_payload(_report_like())

    assert payload["fields"]["summary"] == "Charging defect pattern"
    assert payload["fields"]["issuetype"]["name"] == "Bug"


async def test_linear_payload_format() -> None:
    payload = format_linear_payload(_report_like())

    assert "IssueCreate" in payload["query"]
    assert payload["variables"]["input"]["title"] == "Charging defect pattern"


async def test_dispatch_success_updates_dispatched_at(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-dispatch-success"
    report = await _seed_report(pg_session, tenant_id=tenant_id)
    adapter = _RecordingAdapter(
        OutboundWebhookResponse(
            status_code=201,
            response_body="created",
            success=True,
        )
    )
    service = OutboundDispatchService(
        session=pg_session,
        tenant_runtime=_TenantRuntime(
            channel_type=TenantChannelType.JIRA,
            routing_address="https://jira.example",
            credentials={"auth_header": "Bearer test-token"},
        ),
        adapter=adapter,
        now=lambda: _NOW,
    )

    success = await service.dispatch_report(
        report_id=str(report.report_id),
        tenant_id=tenant_id,
        attempt_number=1,
        expected_tenant_id=tenant_id,
    )
    dispatch = (
        await pg_session.execute(select(OutboundDispatchRow))
    ).scalar_one()

    assert success is True
    assert report.dispatched_at == _NOW
    assert dispatch.status == "success"
    assert dispatch.http_status_code == 201
    assert dispatch.target_url == "https://jira.example/rest/api/3/issue"


async def test_dispatch_failure_creates_failed_record(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-dispatch-failure"
    report = await _seed_report(pg_session, tenant_id=tenant_id)
    adapter = _RecordingAdapter(
        OutboundWebhookResponse(
            status_code=500,
            response_body="server error",
            success=False,
        )
    )
    service = OutboundDispatchService(
        session=pg_session,
        tenant_runtime=_TenantRuntime(
            channel_type=TenantChannelType.LINEAR,
            routing_address="https://api.linear.app/graphql",
            credentials={"api_key": "linear-token"},
        ),
        adapter=adapter,
        now=lambda: _NOW,
    )

    success = await service.dispatch_report(
        report_id=str(report.report_id),
        tenant_id=tenant_id,
        attempt_number=1,
        expected_tenant_id=tenant_id,
    )
    dispatch = (
        await pg_session.execute(select(OutboundDispatchRow))
    ).scalar_one()

    assert success is False
    assert report.dispatched_at is None
    assert dispatch.status == "failed"
    assert dispatch.http_status_code == 500
    assert dispatch.next_retry_at == _NOW + timedelta(seconds=60)


async def test_credentials_never_logged(
    pg_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = "tenant-dispatch-logs"
    report = await _seed_report(pg_session, tenant_id=tenant_id)
    sentinel = "SENTINEL_SECRET_DO_NOT_LOG"
    adapter = _RecordingAdapter(
        OutboundWebhookResponse(
            status_code=201,
            response_body="created",
            success=True,
        )
    )
    service = OutboundDispatchService(
        session=pg_session,
        tenant_runtime=_TenantRuntime(
            channel_type=TenantChannelType.LINEAR,
            routing_address="https://api.linear.app/graphql",
            credentials={"api_key": sentinel},
        ),
        adapter=adapter,
        now=lambda: _NOW,
    )
    caplog.set_level(logging.INFO)

    await service.dispatch_report(
        report_id=str(report.report_id),
        tenant_id=tenant_id,
        attempt_number=1,
        expected_tenant_id=tenant_id,
    )

    assert adapter.requests[0].auth_header == f"Bearer {sentinel}"
    assert sentinel not in caplog.text


async def test_dispatch_tenant_isolation(pg_session: AsyncSession) -> None:
    tenant_a = "tenant-dispatch-a"
    tenant_b = "tenant-dispatch-b"
    report = await _seed_report(pg_session, tenant_id=tenant_a)
    pg_session.add(
        OutboundDispatchRow(
            dispatch_id=uuid.uuid5(
                uuid.UUID("181a3721-c2cc-55ec-99ee-359bf60ac0a1"),
                tenant_a,
            ),
            tenant_id=tenant_a,
            report_id=report.report_id,
            channel_type=TenantChannelType.JIRA.value,
            target_url="https://jira.example/rest/api/3/issue",
            attempt_number=1,
            status="success",
            http_status_code=201,
            dispatched_at=_NOW,
            metadata_json={},
        )
    )
    await pg_session.flush()
    await _ensure_tenant(pg_session, tenant_b)
    await set_pg_rls_tenant(pg_session, tenant_b)

    visible_count = int(
        (
            await pg_session.execute(
                select(func.count()).select_from(OutboundDispatchRow)
            )
        ).scalar_one()
    )

    assert visible_count == 0


async def test_channel_adapter_no_governance_import() -> None:
    source = inspect.getsource(adapter_module)

    assert "governance" not in source


async def _seed_report(
    session: AsyncSession,
    *,
    tenant_id: str,
    governance_status: str = "allowed",
) -> DefectReportRow:
    await _ensure_tenant(session, tenant_id)
    cluster_id = uuid.uuid5(
        uuid.UUID("d1186530-3f80-5312-b94e-bb759329f2b8"),
        tenant_id,
    )
    cluster = DefectClusterRow(
        cluster_id=cluster_id,
        tenant_id=tenant_id,
        category="charging_issue",
        execution_count=5,
        window_hours=24,
        window_start=_NOW - timedelta(hours=1),
        window_end=_NOW,
        threshold_used=5,
        sku_hint=None,
        failure_step_hint=None,
        status="reported",
        metadata_json={"execution_ids": []},
    )
    session.add(cluster)
    report = DefectReportRow(
        report_id=uuid.uuid5(cluster_id, "report"),
        tenant_id=tenant_id,
        cluster_id=cluster_id,
        title="Charging defect pattern",
        executive_summary="Several charging failures share a pattern.",
        failure_pattern="Charging stops under load.",
        customer_impact="Customers cannot reliably charge devices.",
        root_cause_hypothesis="USB-C power path instability.",
        recommended_actions=["Inspect returned units"],
        confidence=0.8,
        evidence_quality="medium",
        incident_count=5,
        governance_status=governance_status,
        metadata_json={},
    )
    session.add(report)
    await session.flush()
    return report


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()


@dataclass(frozen=True, slots=True)
class _ReportLike:
    title: str
    executive_summary: str
    failure_pattern: str
    root_cause_hypothesis: str
    incident_count: int
    confidence: float
    evidence_quality: str


def _report_like() -> _ReportLike:
    return _ReportLike(
        title="Charging defect pattern",
        executive_summary="Several charging failures share a pattern.",
        failure_pattern="Charging stops under load.",
        root_cause_hypothesis="USB-C power path instability.",
        incident_count=5,
        confidence=0.8,
        evidence_quality="medium",
    )


class _RecordingAdapter:
    def __init__(self, response: OutboundWebhookResponse) -> None:
        self.response = response
        self.requests: list[OutboundWebhookRequest] = []

    async def post(
        self,
        request: OutboundWebhookRequest,
    ) -> OutboundWebhookResponse:
        self.requests.append(request)
        return self.response


class _TenantRuntime:
    def __init__(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
        credentials: dict[str, Any],
    ) -> None:
        self._channel_type = channel_type
        self._record = TenantChannelConfigurationRecord(
            config_id=derive_channel_configuration_id(
                tenant_id="tenant-runtime",
                channel_type=channel_type,
            ),
            tenant_id="tenant-runtime",
            channel_type=channel_type,
            status=TenantChannelStatus.ACTIVE,
            routing_address=routing_address,
            credentials_enc=b"unused",
            webhook_secret="unused",
            verified_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
        self._credentials = credentials

    async def list_channels(
        self,
        *,
        tenant_id: str,
        query: TenantChannelConfigurationQuery,
    ) -> TenantChannelConfigurationPage:
        del tenant_id
        if (
            query.channel_type is self._channel_type
            and query.status is TenantChannelStatus.ACTIVE
        ):
            return TenantChannelConfigurationPage(
                items=(self._record,),
                total=1,
                limit=query.limit or 1,
                offset=query.offset,
            )
        return TenantChannelConfigurationPage()

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        del tenant_id
        assert channel_type is self._channel_type
        return self._credentials
