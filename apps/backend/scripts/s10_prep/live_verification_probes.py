#!/usr/bin/env python3
"""S-10 live verification probes.

These probes are intentionally operator-facing: each subcommand prints one
clear PASS/FAIL line and enough evidence for archive screenshots or logs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.runtime.retry_policy import RETRY_POLICIES, RetryPolicy  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.url import build_database_engine_config  # noqa: E402
from app.execution.db.models import ExecutionRow  # noqa: E402
from app.execution.enums import ExecutionKind, ExecutionState  # noqa: E402
from app.queues import QUEUE_DEAD_LETTER, QUEUE_DIAGNOSTIC_RETRY  # noqa: E402
from app.workers.celery_app import celery_app  # noqa: E402
from app.workers.s10_probe_tasks import (  # noqa: E402
    s10_probe_dead_letter_id,
    s10_probe_execution_id,
    s10_probe_session_id,
)

JSON_HEADERS: Final[dict[str, str]] = {"Content-Type": "application/json"}
TENANT_RLS_TABLES: Final[dict[str, str]] = {
    "operational_sessions": "tenant_id",
    "boundary_ingress": "tenant_id",
    "coordination_envelopes": "tenant_id",
    "dead_letter_tasks": "tenant_id",
    "governance_decisions": "tenant_id",
    "tenant_knowledge_documents": "tenant_id",
}
SMOKE_COMPLETION_EVENTS: Final[set[str]] = {
    "diagnostic_analysis_completed",
    "resolution_proposal_created",
    "resolution_outbound_draft_created",
}
SMOKE_FAILURE_EVENTS: Final[set[str]] = {"diagnostic_execution_failed"}
SMOKE_RETRY_BOUND_ERROR_CLASS: Final[str] = "PERSISTENCE_FAILURE"
HTTP_REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0
SMOKE_HTTP_REQUEST_TIMEOUT_SECONDS: Final[float] = 90.0
SMOKE_LIVE_TERMINAL_TIMEOUT_SECONDS: Final[float] = 300.0


class ProbeFailure(RuntimeError):
    """Probe failed before it could collect a normal evidence record."""


class HttpRequestFailure(ProbeFailure):
    """HTTP client failure with fields suitable for probe evidence."""

    error: str
    url: str
    reason: str
    request_timeout_seconds: float | None

    def __init__(
        self,
        *,
        error: str,
        url: str,
        reason: str,
        request_timeout_seconds: float | None = None,
    ) -> None:
        self.error = error
        self.url = url
        self.reason = reason
        self.request_timeout_seconds = request_timeout_seconds
        super().__init__(f"{error} url={url} reason={reason}")


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        value = json.loads(self.body.decode("utf-8"))
        return cast(dict[str, Any], value) if isinstance(value, dict) else {"value": value}


HttpRequest = Callable[
    [str, str, Mapping[str, str] | None, Mapping[str, Any] | None],
    HttpResponse,
]


@dataclass(frozen=True, slots=True)
class SmokeTimelineOutcome:
    terminal: bool
    passed: bool
    status: str
    completion_events: list[dict[str, Any]]
    retry_failure_events: list[dict[str, Any]]
    terminal_failure_events: list[dict[str, Any]]
    grounding_trace: dict[str, Any]
    failure_reason: dict[str, Any] | None = None


def normalize_api_base_url(raw_url: str) -> str:
    base = raw_url.rstrip("/") + "/"
    if base.endswith("/api/v1/"):
        return base
    return urljoin(base, "api/v1/")


def default_http_request(
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
    json_body: Mapping[str, Any] | None = None,
) -> HttpResponse:
    return _http_request(
        method,
        url,
        headers,
        json_body,
        timeout_seconds=HTTP_REQUEST_TIMEOUT_SECONDS,
    )


def _http_request(
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    json_body: Mapping[str, Any] | None,
    *,
    timeout_seconds: float,
) -> HttpResponse:
    payload = (
        None
        if json_body is None
        else json.dumps(json_body, separators=(",", ":")).encode("utf-8")
    )
    request_headers = dict(headers or {})
    if json_body is not None:
        request_headers.update(JSON_HEADERS)
    request = Request(
        url,
        data=payload,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(
                status_code=response.status,
                headers=dict(response.headers),
                body=response.read(),
            )
    except HTTPError as exc:
        return HttpResponse(
            status_code=exc.code,
            headers=dict(exc.headers),
            body=exc.read(),
        )
    except TimeoutError as exc:
        raise HttpRequestFailure(
            error="http_request_timeout",
            url=url,
            reason=str(exc) or "timeout",
            request_timeout_seconds=timeout_seconds,
        ) from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise HttpRequestFailure(
                error="http_request_timeout",
                url=url,
                reason=str(exc.reason) or "timeout",
                request_timeout_seconds=timeout_seconds,
            ) from exc
        raise HttpRequestFailure(
            error="http_request_failed",
            url=url,
            reason=str(exc.reason),
        ) from exc


def _http_request_with_timeout(timeout_seconds: float) -> HttpRequest:
    def request(
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> HttpResponse:
        return _http_request(
            method,
            url,
            headers,
            json_body,
            timeout_seconds=timeout_seconds,
        )

    return request


def run_spoofing_probe(
    *,
    base_url: str,
    forged_tenant_id: str,
    require_detailed_code: bool,
    http_request: HttpRequest = default_http_request,
) -> dict[str, Any]:
    response = http_request(
        "GET",
        urljoin(normalize_api_base_url(base_url), "health"),
        {"X-Tenant-ID": forged_tenant_id},
        None,
    )
    body = response.json()
    error = _extract_error_code(body)
    detailed = error == "header_authority_disabled"
    coarsened = error == "unauthorized"
    passed = response.status_code == 401 and (
        detailed or (coarsened and not require_detailed_code)
    )
    evidence = {
        "status_code": response.status_code,
        "error": error,
        "expected_internal_code": "header_authority_disabled",
        "production_coarsened": coarsened,
        "forged_tenant_id": forged_tenant_id,
    }
    _print_probe_result("spoofing", passed=passed, evidence=evidence)
    return evidence | {"passed": passed}


async def run_rls_probe(
    *,
    database_url: str,
    table: str,
    tenant_a: str,
    tenant_b: str,
    role: str | None,
    require_control_row: bool,
) -> dict[str, Any]:
    tenant_column = _require_rls_table(table)
    settings = get_settings()
    engine_config = build_database_engine_config(
        database_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    engine = create_async_engine(
        engine_config.async_url,
        connect_args=engine_config.connect_args,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            async with session.begin():
                current_user = await _scalar_str(session, "SELECT current_user")
                initial_role = await _scalar_str(session, "SELECT current_role")
                if role:
                    await session.execute(text(f"SET LOCAL ROLE {_quote_ident(role)}"))
                effective_role = await _scalar_str(session, "SELECT current_role")
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                control_count = await _count_rows_for_tenant(
                    session=session,
                    table=table,
                    tenant_column=tenant_column,
                    row_tenant=tenant_b,
                )
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                cross_count = await _count_rows_for_tenant(
                    session=session,
                    table=table,
                    tenant_column=tenant_column,
                    row_tenant=tenant_b,
                )
    finally:
        await engine.dispose()
    passed = cross_count == 0 and (control_count > 0 or not require_control_row)
    evidence = {
        "table": table,
        "row_tenant": tenant_b,
        "session_tenant": tenant_a,
        "control_count_as_row_tenant": control_count,
        "cross_count_as_other_tenant": cross_count,
        "current_user": current_user,
        "initial_role": initial_role,
        "effective_role": effective_role,
        "role_requested": role,
        "require_control_row": require_control_row,
    }
    _print_probe_result("rls", passed=passed, evidence=evidence)
    return evidence | {"passed": passed}


async def run_workers_dlq_probe(
    *,
    database_url: str,
    tenant_id: str,
    probe_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    enqueued_at = datetime.now(timezone.utc).isoformat()
    probe_execution = await _ensure_probe_execution_row(
        database_url=database_url,
        tenant_id=tenant_id,
        probe_id=probe_id,
    )
    expected_dlq_id = s10_probe_dead_letter_id(
        tenant_id=tenant_id,
        probe_id=probe_id,
    )
    async_result = cast(Any, celery_app).send_task(
        "s10_dead_letter_probe",
        kwargs={
            "tenant_id": tenant_id,
            "probe_id": probe_id,
            "enqueued_at": enqueued_at,
            "execution_id": probe_execution["execution_id"],
            "session_id": probe_execution["session_id"],
        },
        queue=QUEUE_DEAD_LETTER,
    )
    deadline = time.monotonic() + timeout_seconds
    row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        row = await _read_dead_letter_row(
            database_url=database_url,
            tenant_id=tenant_id,
            dead_letter_task_id=str(expected_dlq_id),
        )
        if row is not None:
            break
        await asyncio.sleep(poll_interval_seconds)
    evidence = {
        "tenant_id": tenant_id,
        "probe_id": probe_id,
        "execution_id": probe_execution["execution_id"],
        "session_id": probe_execution["session_id"],
        "dispatch_id": probe_execution["dispatch_id"],
        "celery_task_id": str(getattr(async_result, "id", "")),
        "expected_dead_letter_task_id": str(expected_dlq_id),
        "queue": QUEUE_DEAD_LETTER,
        "row": row,
    }
    _print_probe_result("workers_dlq", passed=row is not None, evidence=evidence)
    return evidence | {"passed": row is not None}


async def _ensure_probe_execution_row(
    *,
    database_url: str,
    tenant_id: str,
    probe_id: str,
) -> dict[str, str]:
    settings = get_settings()
    engine_config = build_database_engine_config(
        database_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    engine = create_async_engine(
        engine_config.async_url,
        connect_args=engine_config.connect_args,
    )
    execution_id = s10_probe_execution_id(
        tenant_id=tenant_id,
        probe_id=probe_id,
    )
    session_id = s10_probe_session_id(probe_id=probe_id)
    dispatch_id = f"s10-probe-dispatch:{probe_id}"
    now = datetime.now(timezone.utc)
    metadata = {
        "probe_id": probe_id,
        "purpose": "s10_live_production_worker_dlq_proof",
        "dispatch_id": dispatch_id,
        "session_id": session_id,
        "tenant_id": tenant_id,
    }
    stmt = (
        pg_insert(ExecutionRow)
        .values(
            execution_id=execution_id,
            kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
            state=ExecutionState.DEAD_LETTERED.value,
            attempt_count=0,
            requested_at=now,
            failed_at=now,
            result={
                "status": "dead_lettered",
                "reason": "s10_probe_deliberate_failure",
            },
            error="s10_probe_deliberate_failure",
            metadata_json=metadata,
        )
        .on_conflict_do_update(
            index_elements=[ExecutionRow.execution_id],
            set_={
                ExecutionRow.state: ExecutionState.DEAD_LETTERED.value,
                ExecutionRow.failed_at: now,
                ExecutionRow.result: {
                    "status": "dead_lettered",
                    "reason": "s10_probe_deliberate_failure",
                },
                ExecutionRow.error: "s10_probe_deliberate_failure",
                ExecutionRow.metadata_json: metadata,
            },
        )
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                await session.execute(stmt)
    finally:
        await engine.dispose()
    return {
        "execution_id": str(execution_id),
        "session_id": session_id,
        "dispatch_id": dispatch_id,
    }


def run_smoke_probe(
    *,
    base_url: str,
    tenant_id: str,
    principal_id: str,
    bearer_token: str | None,
    allow_legacy_headers: bool,
    external_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    request_timeout_seconds: float = SMOKE_HTTP_REQUEST_TIMEOUT_SECONDS,
    http_request: HttpRequest = default_http_request,
) -> dict[str, Any]:
    api_base = normalize_api_base_url(base_url)
    effective_http_request = (
        _http_request_with_timeout(request_timeout_seconds)
        if http_request is default_http_request
        else http_request
    )
    headers = _authority_headers(
        tenant_id=tenant_id,
        principal_id=principal_id,
        bearer_token=bearer_token,
        allow_legacy_headers=allow_legacy_headers,
    )
    try:
        ingress = effective_http_request(
            "POST",
            urljoin(api_base, "boundary/translation/ingress"),
            headers,
            {
                "external_id": external_id,
                "channel": "email",
                "raw_content": (
                    "S-10 live smoke: Anker PowerCore stopped charging and "
                    "the customer requests next steps."
                ),
                "language_code": "en",
            },
        )
    except (ProbeFailure, TimeoutError, URLError) as exc:
        evidence = _smoke_request_failure_evidence(
            "ingress",
            exc,
            request_timeout_seconds=request_timeout_seconds,
        )
        _print_probe_result("smoke", passed=False, evidence=evidence)
        return evidence | {"passed": False}
    ingress_body = ingress.json()
    if ingress.status_code != 202:
        evidence = {
            "stage": "ingress",
            "status_code": ingress.status_code,
            "body": ingress_body,
        }
        _print_probe_result("smoke", passed=False, evidence=evidence)
        return evidence | {"passed": False}
    ingress_id = _require_str(ingress_body, "ingress_id")
    canonical_envelope_id = ingress_body.get("canonical_envelope_id")
    try:
        dispatch = effective_http_request(
            "POST",
            urljoin(api_base, "coordination/dispatch"),
            headers,
            {"ingress_id": ingress_id},
        )
    except (ProbeFailure, TimeoutError, URLError) as exc:
        evidence = _smoke_request_failure_evidence(
            "dispatch",
            exc,
            ingress_id=ingress_id,
            request_timeout_seconds=request_timeout_seconds,
        )
        _print_probe_result("smoke", passed=False, evidence=evidence)
        return evidence | {"passed": False}
    dispatch_body = dispatch.json()
    if dispatch.status_code != 200:
        evidence = {
            "stage": "dispatch",
            "status_code": dispatch.status_code,
            "body": dispatch_body,
            "ingress_id": ingress_id,
        }
        _print_probe_result("smoke", passed=False, evidence=evidence)
        return evidence | {"passed": False}
    session_id = _require_str(dispatch_body, "session_id")
    deadline = time.monotonic() + timeout_seconds
    timeline_body: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    outcome = SmokeTimelineOutcome(
        terminal=False,
        passed=False,
        status="not_polled",
        completion_events=[],
        retry_failure_events=[],
        terminal_failure_events=[],
        grounding_trace={},
    )
    poll_count = 0
    while time.monotonic() < deadline:
        poll_count += 1
        try:
            timeline = effective_http_request(
                "GET",
                urljoin(api_base, f"session/{session_id}/timeline"),
                headers,
                None,
            )
        except (ProbeFailure, TimeoutError, URLError) as exc:
            outcome = SmokeTimelineOutcome(
                terminal=True,
                passed=False,
                status="timeline_read_failed",
                completion_events=[],
                retry_failure_events=outcome.retry_failure_events,
                terminal_failure_events=outcome.terminal_failure_events,
                grounding_trace=outcome.grounding_trace,
                failure_reason=_smoke_request_failure_evidence(
                    "timeline",
                    exc,
                    session_id=session_id,
                    poll_count=poll_count,
                    request_timeout_seconds=request_timeout_seconds,
                ),
            )
            break
        timeline_body = timeline.json()
        if timeline.status_code != 200:
            outcome = SmokeTimelineOutcome(
                terminal=True,
                passed=False,
                status="timeline_read_failed",
                completion_events=[],
                retry_failure_events=[],
                terminal_failure_events=[],
                grounding_trace={},
                failure_reason={
                    "status_code": timeline.status_code,
                    "body": timeline_body,
                },
            )
            break
        events = _list_of_dicts(timeline_body.get("events"))
        outcome = _classify_smoke_timeline_outcome(events)
        if outcome.terminal:
            break
        time.sleep(poll_interval_seconds)
    event_types = [
        str(event.get("event_type"))
        for event in events
    ]
    if not outcome.terminal:
        outcome = SmokeTimelineOutcome(
            terminal=True,
            passed=False,
            status="timeout",
            completion_events=outcome.completion_events,
            retry_failure_events=outcome.retry_failure_events,
            terminal_failure_events=outcome.terminal_failure_events,
            grounding_trace=outcome.grounding_trace,
            failure_reason={
                "message": f"did not reach terminal within {timeout_seconds}s"
            },
        )
    retry_bound_seconds = _smoke_retry_wait_bound_seconds()
    evidence = {
        "external_id": external_id,
        "ingress_id": ingress_id,
        "canonical_envelope_id": canonical_envelope_id,
        "dispatch_id": dispatch_body.get("dispatch_id"),
        "session_id": session_id,
        "execution_id": dispatch_body.get("execution_id"),
        "governance_decision_id": dispatch_body.get("governance_decision_id"),
        "timeline_event_count": len(event_types),
        "timeline_event_types": event_types,
        "poll_count": poll_count,
        "terminal_status": outcome.status,
        "timeout_seconds": timeout_seconds,
        "timeout_source": "live end-to-end smoke terminal wait",
        "poll_interval_seconds": poll_interval_seconds,
        "request_timeout_seconds": request_timeout_seconds,
        "retry_wait_bound_seconds": retry_bound_seconds,
        "retry_wait_bound_source": (
            f"{SMOKE_RETRY_BOUND_ERROR_CLASS} policy retry countdowns plus "
            "AI_TIMEOUT_SECONDS completion grace"
        ),
        "completion_event_types": [
            str(event.get("event_type")) for event in outcome.completion_events
        ],
        "retry_failure_event_count": len(outcome.retry_failure_events),
        "terminal_failure_event_count": len(outcome.terminal_failure_events),
        "failure_reason": outcome.failure_reason,
        "grounding_trace": outcome.grounding_trace,
    }
    _print_probe_result("smoke", passed=outcome.passed, evidence=evidence)
    return evidence | {"passed": outcome.passed}


def _smoke_request_failure_evidence(
    stage: str,
    exc: ProbeFailure | TimeoutError | URLError,
    **context: Any,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"stage": stage, **context}
    if isinstance(exc, HttpRequestFailure):
        evidence.update(
            {
                "error": exc.error,
                "url": exc.url,
                "reason": exc.reason,
            }
        )
        if exc.request_timeout_seconds is not None:
            evidence["request_timeout_seconds"] = exc.request_timeout_seconds
        return evidence
    if isinstance(exc, TimeoutError):
        evidence.update(
            {
                "error": "http_request_timeout",
                "reason": str(exc) or "timeout",
                "request_timeout_seconds": evidence.get(
                    "request_timeout_seconds",
                    HTTP_REQUEST_TIMEOUT_SECONDS,
                ),
            }
        )
        return evidence
    if isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError):
        evidence.update(
            {
                "error": "http_request_timeout",
                "reason": str(exc.reason) or "timeout",
                "request_timeout_seconds": evidence.get(
                    "request_timeout_seconds",
                    HTTP_REQUEST_TIMEOUT_SECONDS,
                ),
            }
        )
        return evidence
    reason = str(exc.reason) if isinstance(exc, URLError) else str(exc)
    evidence.update({"error": "http_request_failed", "reason": reason})
    return evidence


def _authority_headers(
    *,
    tenant_id: str,
    principal_id: str,
    bearer_token: str | None,
    allow_legacy_headers: bool,
) -> dict[str, str]:
    if bearer_token:
        return {"Authorization": f"Bearer {bearer_token}"}
    if allow_legacy_headers:
        return {"X-Tenant-ID": tenant_id, "X-Principal-ID": principal_id}
    raise ProbeFailure(
        "smoke requires --bearer-token or OPERIOUS_API_TOKEN for production; "
        "use --allow-legacy-headers only against a local non-production server"
    )


def _extract_grounding_trace(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in events:
        payload_value = event.get("payload")
        if not isinstance(payload_value, dict):
            continue
        payload = cast(Mapping[str, Any], payload_value)
        citations = payload.get("retrieved_citations")
        evidence = payload.get("evidence")
        if citations:
            return {"source": "retrieved_citations", "items": citations}
        if evidence:
            return {"source": "resolution_evidence", "items": evidence}
        governance_decision_id = payload.get("governance_decision_id")
        if governance_decision_id:
            return {
                "source": "governance_decision_id",
                "governance_decision_id": governance_decision_id,
            }
    return {}


def _classify_smoke_timeline_outcome(
    events: list[dict[str, Any]],
) -> SmokeTimelineOutcome:
    completion_events = [
        event
        for event in events
        if str(event.get("event_type")) in SMOKE_COMPLETION_EVENTS
    ]
    grounding_trace = _extract_grounding_trace(completion_events)
    if completion_events:
        if grounding_trace:
            return SmokeTimelineOutcome(
                terminal=True,
                passed=True,
                status="completed",
                completion_events=completion_events,
                retry_failure_events=_smoke_retry_failure_events(events),
                terminal_failure_events=[],
                grounding_trace=grounding_trace,
            )
        return SmokeTimelineOutcome(
            terminal=True,
            passed=False,
            status="completed_missing_grounding_trace",
            completion_events=completion_events,
            retry_failure_events=_smoke_retry_failure_events(events),
            terminal_failure_events=[],
            grounding_trace={},
            failure_reason={
                "message": (
                    "observed diagnostic completion but no grounding trace "
                    "was present in completion events"
                )
            },
        )

    terminal_failure_events = [
        event
        for event in events
        if _is_terminal_smoke_failure_event(event)
    ]
    if terminal_failure_events:
        return SmokeTimelineOutcome(
            terminal=True,
            passed=False,
            status="terminal_failure",
            completion_events=[],
            retry_failure_events=_smoke_retry_failure_events(events),
            terminal_failure_events=terminal_failure_events,
            grounding_trace={},
            failure_reason=_smoke_failure_reason(terminal_failure_events[-1]),
        )

    retry_failure_events = _smoke_retry_failure_events(events)
    return SmokeTimelineOutcome(
        terminal=False,
        passed=False,
        status="retrying" if retry_failure_events else "waiting",
        completion_events=[],
        retry_failure_events=retry_failure_events,
        terminal_failure_events=[],
        grounding_trace={},
    )


def _smoke_retry_failure_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if str(event.get("event_type")) in SMOKE_FAILURE_EVENTS
        and _is_retrying_smoke_failure_event(event)
    ]


def _is_retrying_smoke_failure_event(event: Mapping[str, Any]) -> bool:
    payload = _event_payload(event)
    return (
        payload.get("retry_requested") is True
        or payload.get("retry_queue") == QUEUE_DIAGNOSTIC_RETRY
    )


def _is_terminal_smoke_failure_event(event: Mapping[str, Any]) -> bool:
    if str(event.get("event_type")) not in SMOKE_FAILURE_EVENTS:
        return False
    payload = _event_payload(event)
    return (
        payload.get("retry_requested") is False
        or payload.get("retry_queue") == QUEUE_DEAD_LETTER
    )


def _smoke_failure_reason(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = _event_payload(event)
    return {
        "event_type": str(event.get("event_type")),
        "error_class": payload.get("error_class"),
        "error_message": payload.get("error_message"),
        "retry_requested": payload.get("retry_requested"),
        "retry_queue": payload.get("retry_queue"),
        "retry_countdown_seconds": payload.get("retry_countdown_seconds"),
    }


def _event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        return cast(Mapping[str, Any], payload)
    return {}


def _smoke_retry_wait_bound_seconds() -> float:
    policy = RETRY_POLICIES[SMOKE_RETRY_BOUND_ERROR_CLASS]
    settings = get_settings()
    return float(
        _retry_countdown_window_seconds(policy)
        + settings.AI_TIMEOUT_SECONDS
    )


def _retry_countdown_window_seconds(policy: RetryPolicy) -> int:
    return sum(
        int(policy.base_delay_seconds * (policy.backoff_multiplier ** retry_count))
        for retry_count in range(policy.max_retries)
    )


async def _read_dead_letter_row(
    *,
    database_url: str,
    tenant_id: str,
    dead_letter_task_id: str,
) -> dict[str, Any] | None:
    settings = get_settings()
    engine_config = build_database_engine_config(
        database_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    engine = create_async_engine(
        engine_config.async_url,
        connect_args=engine_config.connect_args,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                result = await session.execute(
                    text(
                        """
                        SELECT dead_letter_task_id::text AS dead_letter_task_id,
                               task_name,
                               task_id,
                               execution_id::text AS execution_id,
                               queue,
                               reason,
                               retry_count,
                               metadata
                        FROM dead_letter_tasks
                        WHERE dead_letter_task_id = :dead_letter_task_id
                        """
                    ),
                    {"dead_letter_task_id": dead_letter_task_id},
                )
                row = result.mappings().one_or_none()
                return None if row is None else dict(row)
    finally:
        await engine.dispose()


async def _scalar_str(session: Any, sql: str) -> str:
    value = (await session.execute(text(sql))).scalar_one()
    return str(value)


async def _count_rows_for_tenant(
    *,
    session: Any,
    table: str,
    tenant_column: str,
    row_tenant: str,
) -> int:
    result = await session.execute(
        text(
            "SELECT COUNT(*) FROM "
            f"public.{_quote_ident(table)} "
            f"WHERE {_quote_ident(tenant_column)} = :row_tenant"
        ),
        {"row_tenant": row_tenant},
    )
    return int(result.scalar_one())


def _require_rls_table(table: str) -> str:
    try:
        return TENANT_RLS_TABLES[table]
    except KeyError as exc:
        allowed = ", ".join(sorted(TENANT_RLS_TABLES))
        raise ProbeFailure(f"unsupported RLS probe table {table!r}; allowed: {allowed}") from exc


def _quote_ident(identifier: str) -> str:
    if not identifier or any(ch not in "_0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for ch in identifier):
        raise ProbeFailure(f"unsafe SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def _extract_error_code(body: Mapping[str, Any]) -> str | None:
    error = body.get("error")
    if isinstance(error, str):
        return error
    detail = body.get("detail")
    if isinstance(detail, Mapping):
        detail = cast(Mapping[str, Any], detail)
        code = detail.get("code") or detail.get("error")
        return code if isinstance(code, str) else None
    return None


def _require_str(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if isinstance(value, str) and value:
        return value
    raise ProbeFailure(f"response field {key!r} missing or empty: {body}")


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = cast(list[Any], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _print_probe_result(
    name: str,
    *,
    passed: bool,
    evidence: Mapping[str, Any],
) -> None:
    status = "PASS" if passed else "FAIL"
    print(f"{status} {name} {json.dumps(evidence, sort_keys=True, default=str)}")


def _database_url_arg(value: str | None) -> str:
    if value:
        return value
    env_value = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if env_value:
        return env_value
    return get_settings().database_url


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    spoof = subcommands.add_parser("spoofing")
    spoof.add_argument("--base-url", required=True)
    spoof.add_argument("--forged-tenant-id", default="forged-tenant")
    spoof.add_argument("--require-detailed-code", action="store_true")

    rls = subcommands.add_parser("rls")
    rls.add_argument("--database-url")
    rls.add_argument("--table", choices=sorted(TENANT_RLS_TABLES), default="operational_sessions")
    rls.add_argument("--tenant-a", required=True)
    rls.add_argument("--tenant-b", required=True)
    rls.add_argument("--role", default="operious_app")
    rls.add_argument("--no-set-role", action="store_true")
    rls.add_argument("--allow-empty-control", action="store_true")

    dlq = subcommands.add_parser("workers-dlq")
    dlq.add_argument("--database-url")
    dlq.add_argument("--tenant-id", default="anker-pilot")
    dlq.add_argument("--probe-id", default=f"s10-{uuid.uuid4().hex}")
    dlq.add_argument("--timeout-seconds", type=float, default=60.0)
    dlq.add_argument("--poll-interval-seconds", type=float, default=2.0)

    smoke = subcommands.add_parser("smoke")
    smoke.add_argument("--base-url", required=True)
    smoke.add_argument("--tenant-id", default="anker-pilot")
    smoke.add_argument("--principal-id", default="s10-live-probe")
    smoke.add_argument("--bearer-token", default=os.environ.get("OPERIOUS_API_TOKEN"))
    smoke.add_argument("--allow-legacy-headers", action="store_true")
    smoke.add_argument("--external-id", default=f"s10-smoke-{uuid.uuid4().hex}")
    smoke.add_argument(
        "--timeout-seconds",
        type=float,
        default=SMOKE_LIVE_TERMINAL_TIMEOUT_SECONDS,
    )
    smoke.add_argument("--poll-interval-seconds", type=float, default=3.0)
    smoke.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=SMOKE_HTTP_REQUEST_TIMEOUT_SECONDS,
        help=(
            "Per-HTTP-request timeout for the smoke ingress, dispatch, and "
            "timeline calls."
        ),
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    try:
        if args.command == "spoofing":
            result = run_spoofing_probe(
                base_url=args.base_url,
                forged_tenant_id=args.forged_tenant_id,
                require_detailed_code=args.require_detailed_code,
            )
        elif args.command == "rls":
            result = await run_rls_probe(
                database_url=_database_url_arg(args.database_url),
                table=args.table,
                tenant_a=args.tenant_a,
                tenant_b=args.tenant_b,
                role=None if args.no_set_role else args.role,
                require_control_row=not args.allow_empty_control,
            )
        elif args.command == "workers-dlq":
            result = await run_workers_dlq_probe(
                database_url=_database_url_arg(args.database_url),
                tenant_id=args.tenant_id,
                probe_id=args.probe_id,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        elif args.command == "smoke":
            result = run_smoke_probe(
                base_url=args.base_url,
                tenant_id=args.tenant_id,
                principal_id=args.principal_id,
                bearer_token=args.bearer_token,
                allow_legacy_headers=args.allow_legacy_headers,
                external_id=args.external_id,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                request_timeout_seconds=args.request_timeout_seconds,
            )
        else:  # pragma: no cover - argparse prevents this.
            raise ProbeFailure(f"unknown probe command {args.command!r}")
    except ProbeFailure as exc:
        print(f"FAIL {args.command} {exc}", file=sys.stderr)
        return 2
    return 0 if result["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main_async(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
