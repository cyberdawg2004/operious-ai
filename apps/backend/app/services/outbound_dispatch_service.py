"""Outbound dispatch service for governed defect reports."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.outbound import (
    OutboundWebhookAdapter,
    OutboundWebhookRequest,
    OutboundWebhookResponse,
    format_jira_payload,
    format_linear_payload,
)
from app.core.config import get_settings
from app.runtime.db.models import DefectReportRow, OutboundDispatchRow
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime

_DEFAULT_TIMEOUT_SECONDS = 10.0
_FAILED_RESPONSE_BODY_LIMIT = 2048
_UNCONFIGURED_CHANNEL = "unconfigured"
_UNCONFIGURED_TARGET = "unconfigured"
_RETRY_BASE_SECONDS = 60


class OutboundDispatchError(RuntimeError):
    """Base outbound dispatch failure."""


class OutboundDispatchConfigurationError(OutboundDispatchError):
    """Tenant outbound channel configuration is missing or invalid."""


class OutboundDispatchNotFoundError(OutboundDispatchError):
    """The requested defect report does not exist for the tenant."""


class OutboundWebhookAdapterProtocol(Protocol):
    async def post(
        self,
        request: OutboundWebhookRequest,
    ) -> OutboundWebhookResponse: ...


class TenantCredentialRuntimeProtocol(Protocol):
    async def list_channels(
        self,
        *,
        tenant_id: str,
        query: TenantChannelConfigurationQuery,
    ) -> TenantChannelConfigurationPage: ...

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _OutboundChannel:
    channel_type: TenantChannelType
    target_url: str
    auth_header: str


@dataclass(frozen=True, slots=True)
class _ReportPayload:
    title: str
    executive_summary: str
    failure_pattern: str
    root_cause_hypothesis: str
    incident_count: int
    confidence: float
    evidence_quality: str


class OutboundDispatchService:
    """Fetch tenant credentials, deliver a report, and record the outcome."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        tenant_runtime: TenantCredentialRuntimeProtocol | None = None,
        adapter: OutboundWebhookAdapterProtocol | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._tenant_runtime = tenant_runtime
        self._adapter = adapter or OutboundWebhookAdapter()
        self._now = now or _utcnow

    async def dispatch_report(
        self,
        *,
        report_id: str,
        tenant_id: str,
        attempt_number: int,
        expected_tenant_id: str,
    ) -> bool:
        if tenant_id != expected_tenant_id:
            raise ValueError("tenant_id does not match expected_tenant_id")
        if attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")

        report = await self._load_report(
            report_id=report_id,
            expected_tenant_id=expected_tenant_id,
        )
        if report.governance_status != "allowed":
            await self._record_unattempted_failure(
                report=report,
                attempt_number=attempt_number,
                reason="defect report is not governance-allowed",
            )
            return False
        if report.dispatched_at is not None:
            return True

        try:
            channel = await self._resolve_channel(tenant_id=tenant_id)
            payload = _format_payload(channel.channel_type, report)
        except OutboundDispatchConfigurationError as exc:
            await self._record_unattempted_failure(
                report=report,
                attempt_number=attempt_number,
                reason=str(exc),
            )
            return False

        dispatch = OutboundDispatchRow(
            dispatch_id=uuid.uuid4(),  # EPHEMERAL: dispatch attempt ledger row id.
            tenant_id=tenant_id,
            report_id=report.report_id,
            channel_type=channel.channel_type.value,
            target_url=channel.target_url,
            attempt_number=attempt_number,
            status="pending",
            metadata_json={"report_id": str(report.report_id)},
        )
        self._session.add(dispatch)
        await self._session.flush()

        attempted_at = self._now()
        try:
            response = await self._adapter.post(
                OutboundWebhookRequest(
                    url=channel.target_url,
                    payload=payload,
                    auth_header=channel.auth_header,
                    channel_type=channel.channel_type.value,
                    timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
                )
            )
        except Exception as exc:  # noqa: BLE001
            dispatch.status = "failed"
            dispatch.error_message = exc.__class__.__name__
            dispatch.dispatched_at = attempted_at
            dispatch.next_retry_at = _next_retry_at(
                attempted_at=attempted_at,
                attempt_number=attempt_number,
            )
            await self._session.flush()
            return False

        dispatch.http_status_code = response.status_code
        dispatch.response_body = response.response_body[:_FAILED_RESPONSE_BODY_LIMIT]
        dispatch.dispatched_at = attempted_at
        if response.success:
            dispatch.status = "success"
            report.dispatched_at = attempted_at
            await self._session.flush()
            return True

        dispatch.status = "failed"
        dispatch.error_message = f"http_status_{response.status_code}"
        dispatch.next_retry_at = _next_retry_at(
            attempted_at=attempted_at,
            attempt_number=attempt_number,
        )
        await self._session.flush()
        return False

    async def mark_dead_lettered(
        self,
        *,
        report_id: str,
        tenant_id: str,
        attempt_number: int,
        reason: str,
    ) -> None:
        parsed_report_id = _parse_uuid(report_id, "report_id")
        stmt = (
            select(OutboundDispatchRow)
            .where(
                OutboundDispatchRow.tenant_id == tenant_id,
                OutboundDispatchRow.report_id == parsed_report_id,
                OutboundDispatchRow.attempt_number == attempt_number,
            )
            .order_by(OutboundDispatchRow.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = OutboundDispatchRow(
                dispatch_id=uuid.uuid4(),  # EPHEMERAL: dispatch attempt ledger row id.
                tenant_id=tenant_id,
                report_id=parsed_report_id,
                channel_type=_UNCONFIGURED_CHANNEL,
                target_url=_UNCONFIGURED_TARGET,
                attempt_number=attempt_number,
                status="dead_lettered",
                error_message=reason,
                dispatched_at=self._now(),
                metadata_json={"report_id": report_id},
            )
            self._session.add(row)
        else:
            row.status = "dead_lettered"
            row.error_message = reason
        await self._session.flush()

    async def _load_report(
        self,
        *,
        report_id: str,
        expected_tenant_id: str,
    ) -> DefectReportRow:
        parsed_report_id = _parse_uuid(report_id, "report_id")
        report = await self._session.get(DefectReportRow, parsed_report_id)
        if report is None or report.tenant_id != expected_tenant_id:
            raise OutboundDispatchNotFoundError("defect report not found")
        return report

    async def _resolve_channel(self, *, tenant_id: str) -> _OutboundChannel:
        tenant_runtime = self._tenant_runtime or _build_tenant_runtime(self._session)
        for channel_type in (TenantChannelType.JIRA, TenantChannelType.LINEAR):
            page = await tenant_runtime.list_channels(
                tenant_id=tenant_id,
                query=TenantChannelConfigurationQuery(
                    channel_type=channel_type,
                    status=TenantChannelStatus.ACTIVE,
                    limit=1,
                ),
            )
            if not page.items:
                continue
            record = page.items[0]
            credentials = await tenant_runtime.load_channel_credentials(
                tenant_id=tenant_id,
                channel_type=channel_type,
            )
            target_url = _target_url(
                channel_type=channel_type,
                routing_address=record.routing_address,
                credentials=credentials,
            )
            auth_header = _auth_header(credentials)
            return _OutboundChannel(
                channel_type=channel_type,
                target_url=target_url,
                auth_header=auth_header,
            )
        raise OutboundDispatchConfigurationError(
            "no active jira or linear channel configured"
        )

    async def _record_unattempted_failure(
        self,
        *,
        report: DefectReportRow,
        attempt_number: int,
        reason: str,
    ) -> None:
        now = self._now()
        row = OutboundDispatchRow(
            dispatch_id=uuid.uuid4(),  # EPHEMERAL: dispatch attempt ledger row id.
            tenant_id=report.tenant_id,
            report_id=report.report_id,
            channel_type=_UNCONFIGURED_CHANNEL,
            target_url=_UNCONFIGURED_TARGET,
            attempt_number=attempt_number,
            status="failed",
            error_message=reason,
            next_retry_at=_next_retry_at(
                attempted_at=now,
                attempt_number=attempt_number,
            ),
            dispatched_at=now,
            metadata_json={"report_id": str(report.report_id)},
        )
        self._session.add(row)
        await self._session.flush()


def _build_tenant_runtime(session: AsyncSession) -> TenantConfigurationRuntime:
    key = get_settings().TENANT_CREDENTIAL_MASTER_KEY
    if not key.strip():
        raise OutboundDispatchConfigurationError(
            "tenant credential master key is required"
        )
    return TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=TenantCredentialEncryptor(platform_master_key=key),
    )


def _format_payload(
    channel_type: TenantChannelType,
    report: DefectReportRow,
) -> dict[str, Any]:
    payload = _report_payload(report)
    if channel_type is TenantChannelType.JIRA:
        return format_jira_payload(payload)
    if channel_type is TenantChannelType.LINEAR:
        return format_linear_payload(payload)
    raise OutboundDispatchConfigurationError(
        f"unsupported outbound channel type: {channel_type.value}"
    )


def _report_payload(report: DefectReportRow) -> _ReportPayload:
    return _ReportPayload(
        title=str(report.title),
        executive_summary=str(report.executive_summary),
        failure_pattern=str(report.failure_pattern),
        root_cause_hypothesis=str(report.root_cause_hypothesis),
        incident_count=int(report.incident_count),
        confidence=float(report.confidence),
        evidence_quality=str(report.evidence_quality),
    )


def _target_url(
    *,
    channel_type: TenantChannelType,
    routing_address: str,
    credentials: Mapping[str, Any],
) -> str:
    configured = _credential_string(
        credentials,
        "url",
        "webhook_url",
        "target_url",
    )
    raw_url = configured or routing_address
    if not raw_url.strip():
        raise OutboundDispatchConfigurationError("outbound target url is required")
    if channel_type is TenantChannelType.JIRA:
        return _jira_issue_url(raw_url)
    return raw_url


def _jira_issue_url(raw_url: str) -> str:
    stripped = raw_url.strip().rstrip("/")
    if stripped.endswith("/rest/api/3/issue"):
        return stripped
    return f"{stripped}/rest/api/3/issue"


def _auth_header(credentials: Mapping[str, Any]) -> str:
    direct = _credential_string(credentials, "auth_header", "authorization")
    if direct is not None:
        return direct

    username = _credential_string(credentials, "username", "email")
    basic_secret = _credential_string(credentials, "api_token", "password")
    if username is not None and basic_secret is not None:
        token = base64.b64encode(f"{username}:{basic_secret}".encode("utf-8"))
        return f"Basic {token.decode('ascii')}"

    bearer = _credential_string(
        credentials,
        "bearer_token",
        "access_token",
        "api_key",
        "token",
    )
    if bearer is not None:
        return f"Bearer {bearer}"
    raise OutboundDispatchConfigurationError("outbound auth header is required")


def _credential_string(
    credentials: Mapping[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = credentials.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _next_retry_at(
    *,
    attempted_at: datetime,
    attempt_number: int,
) -> datetime:
    delay = _RETRY_BASE_SECONDS * (2 ** max(0, attempt_number - 1))
    return attempted_at + timedelta(seconds=delay)


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "OutboundDispatchConfigurationError",
    "OutboundDispatchError",
    "OutboundDispatchNotFoundError",
    "OutboundDispatchService",
]
