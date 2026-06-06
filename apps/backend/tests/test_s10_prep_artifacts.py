"""S-10 production-proof artifacts."""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_protection.crypto import DataProtectionService, MasterKeyRing
from app.data_protection.db.models import DataProtectionDataKeyRow
from app.queues import QUEUE_DEAD_LETTER
from app.tenant.chronology import canonical_sha256
from app.tenant.db.models import (
    TenantKnowledgeDocumentRow,
    TenantKnowledgeDocumentVersionRow,
    TenantRow,
)
from app.workers.celery_app import celery_app
from app.workers.s10_probe_tasks import (
    s10_dead_letter_probe,
    s10_probe_dead_letter_id,
)
import scripts.s10_prep.live_verification_probes as live_probes
from scripts.s10_prep.live_verification_probes import (
    HttpResponse,
    normalize_api_base_url,
    run_smoke_probe,
    run_spoofing_probe,
)
from scripts.s10_prep.rewrap_legacy_anker_knowledge import (
    ENVELOPE_TEXT_PREFIX,
    content_scheme,
    run_rewrap,
)
from tests.conftest import requires_postgres

_TENANT_ID = "s10-artifacts-tenant"
_DOCUMENT_TITLE = "S-10 seeded legacy Anker record"
_DOCUMENT_CONTENT = "Legacy-direct seeded Anker policy content."
_DOCUMENT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "s10-artifacts-document")
_NOW = datetime(2026, 6, 3, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


@pytest.mark.asyncio
@requires_postgres
async def test_legacy_rewrap_dry_run_execute_and_second_execute_noop(
    pg_session: AsyncSession,
) -> None:
    await _seed_legacy_knowledge(
        pg_session,
        document_id=_DOCUMENT_ID,
        content=_DOCUMENT_CONTENT,
    )
    service = _data_protection(pg_session)

    dry_run = await run_rewrap(
        pg_session,
        data_protection=service,
        tenant_id=_TENANT_ID,
        titles=(_DOCUMENT_TITLE,),
        execute=False,
    )

    assert dry_run.dry_run is True
    assert dry_run.changed_documents == 1
    assert dry_run.changed_versions == 1
    assert dry_run.hash_verified_versions == 1
    document, version = await _load_knowledge_rows(pg_session, _DOCUMENT_ID)
    assert content_scheme(document.content) == "legacy-direct"
    assert content_scheme(version.content) == "legacy-direct"
    assert await _data_key_count(pg_session) == 0

    executed = await run_rewrap(
        pg_session,
        data_protection=service,
        tenant_id=_TENANT_ID,
        titles=(_DOCUMENT_TITLE,),
        execute=True,
    )

    assert executed.dry_run is False
    assert executed.changed_documents == 1
    assert executed.changed_versions == 1
    document, version = await _load_knowledge_rows(pg_session, _DOCUMENT_ID)
    assert document.content.startswith(ENVELOPE_TEXT_PREFIX)
    assert version.content.startswith(ENVELOPE_TEXT_PREFIX)
    assert await service.decrypt_text(document.content) == _DOCUMENT_CONTENT
    assert await service.decrypt_text(version.content) == _DOCUMENT_CONTENT
    assert version.content_sha256 == _version_hash(plaintext=_DOCUMENT_CONTENT)
    assert await _data_key_count(pg_session) == 1

    second = await run_rewrap(
        pg_session,
        data_protection=service,
        tenant_id=_TENANT_ID,
        titles=(_DOCUMENT_TITLE,),
        execute=True,
    )

    assert second.changed_documents == 0
    assert second.changed_versions == 0
    assert second.legacy_documents == 0
    assert second.legacy_versions == 0


def test_spoofing_probe_accepts_production_coarsened_auth_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_http_request(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        json_body: Mapping[str, Any] | None,
    ) -> HttpResponse:
        del method, url, headers, json_body
        return HttpResponse(
            status_code=401,
            headers={},
            body=b'{"error":"unauthorized"}',
        )

    result = run_spoofing_probe(
        base_url="https://example.test",
        forged_tenant_id="forged",
        require_detailed_code=False,
        http_request=fake_http_request,
    )

    assert result["passed"] is True
    assert "PASS spoofing" in capsys.readouterr().out


def test_smoke_probe_prints_reconstructible_grounding_trace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_http_request(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        json_body: Mapping[str, Any] | None,
    ) -> HttpResponse:
        del headers, json_body
        calls.append((method, url))
        if url.endswith("/boundary/translation/ingress"):
            return _json_response(
                202,
                {
                    "ingress_id": "ingress-smoke",
                    "canonical_envelope_id": "envelope-smoke",
                },
            )
        if url.endswith("/coordination/dispatch"):
            return _json_response(
                200,
                {
                    "dispatch_id": "dispatch-smoke",
                    "session_id": "11111111-1111-1111-1111-111111111111",
                    "execution_id": "execution-smoke",
                    "governance_decision_id": "governance-smoke",
                    "verdict": "allow",
                },
            )
        if url.endswith("/session/11111111-1111-1111-1111-111111111111/timeline"):
            return _json_response(
                200,
                {
                    "events": [
                        {
                            "event_type": "resolution_proposal_created",
                            "payload": {
                                "proposal_id": "proposal-smoke",
                                "governance_decision_id": "governance-smoke",
                                "evidence": [
                                    {
                                        "document_id": "doc-1",
                                        "char_start": 0,
                                        "char_end": 16,
                                    }
                                ],
                            },
                        }
                    ],
                    "total": 1,
                },
            )
        return _json_response(404, {"detail": {"code": "not_found"}})

    result = run_smoke_probe(
        base_url="https://example.test/api/v1",
        tenant_id="anker-pilot",
        principal_id="operator",
        bearer_token="token",
        allow_legacy_headers=False,
        external_id="s10-smoke-test",
        timeout_seconds=0.1,
        poll_interval_seconds=0.01,
        http_request=fake_http_request,
    )

    assert result["passed"] is True
    assert result["grounding_trace"]["source"] == "resolution_evidence"
    assert calls[0] == (
        "POST",
        "https://example.test/api/v1/boundary/translation/ingress",
    )
    assert "PASS smoke" in capsys.readouterr().out


def test_smoke_probe_waits_through_retry_before_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    timeline_calls = 0

    def fake_http_request(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        json_body: Mapping[str, Any] | None,
    ) -> HttpResponse:
        del method, headers, json_body
        nonlocal timeline_calls
        if url.endswith("/boundary/translation/ingress"):
            return _json_response(
                202,
                {
                    "ingress_id": "ingress-smoke",
                    "canonical_envelope_id": "envelope-smoke",
                },
            )
        if url.endswith("/coordination/dispatch"):
            return _json_response(
                200,
                {
                    "dispatch_id": "dispatch-smoke",
                    "session_id": "11111111-1111-1111-1111-111111111111",
                    "execution_id": "execution-smoke",
                },
            )
        if url.endswith("/session/11111111-1111-1111-1111-111111111111/timeline"):
            timeline_calls += 1
            if timeline_calls == 1:
                return _json_response(
                    200,
                    {
                        "events": [
                            {
                                "event_type": "diagnostic_execution_failed",
                                "payload": {
                                    "error_class": "PERSISTENCE_FAILURE",
                                    "retry_requested": True,
                                    "retry_queue": "diagnostic.retry",
                                    "retry_countdown_seconds": 15,
                                },
                            }
                        ]
                    },
                )
            return _json_response(
                200,
                {
                    "events": [
                        {
                            "event_type": "diagnostic_execution_failed",
                            "payload": {
                                "error_class": "PERSISTENCE_FAILURE",
                                "retry_requested": True,
                                "retry_queue": "diagnostic.retry",
                                "retry_countdown_seconds": 15,
                            },
                        },
                        {
                            "event_type": "resolution_proposal_created",
                            "payload": {
                                "proposal_id": "proposal-smoke",
                                "evidence": [{"document_id": "doc-1"}],
                            },
                        },
                    ]
                },
            )
        return _json_response(404, {"detail": {"code": "not_found"}})

    result = run_smoke_probe(
        base_url="https://example.test/api/v1",
        tenant_id="anker-pilot",
        principal_id="operator",
        bearer_token="token",
        allow_legacy_headers=False,
        external_id="s10-smoke-test",
        timeout_seconds=1.0,
        poll_interval_seconds=0.01,
        http_request=fake_http_request,
    )

    assert result["passed"] is True
    assert result["terminal_status"] == "completed"
    assert result["retry_failure_event_count"] == 1
    assert result["poll_count"] == 2
    assert "PASS smoke" in capsys.readouterr().out


def test_smoke_probe_reports_terminal_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_http_request(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        json_body: Mapping[str, Any] | None,
    ) -> HttpResponse:
        del method, headers, json_body
        if url.endswith("/boundary/translation/ingress"):
            return _json_response(
                202,
                {"ingress_id": "ingress-smoke"},
            )
        if url.endswith("/coordination/dispatch"):
            return _json_response(
                200,
                {
                    "dispatch_id": "dispatch-smoke",
                    "session_id": "11111111-1111-1111-1111-111111111111",
                    "execution_id": "execution-smoke",
                },
            )
        if url.endswith("/session/11111111-1111-1111-1111-111111111111/timeline"):
            return _json_response(
                200,
                {
                    "events": [
                        {
                            "event_type": "diagnostic_execution_failed",
                            "payload": {
                                "error_class": "SEMANTIC_REJECTION",
                                "error_message": "semantic drift",
                                "retry_requested": False,
                                "retry_queue": "dead_letter",
                                "retry_countdown_seconds": 0,
                            },
                        }
                    ]
                },
            )
        return _json_response(404, {"detail": {"code": "not_found"}})

    result = run_smoke_probe(
        base_url="https://example.test/api/v1",
        tenant_id="anker-pilot",
        principal_id="operator",
        bearer_token="token",
        allow_legacy_headers=False,
        external_id="s10-smoke-test",
        timeout_seconds=1.0,
        poll_interval_seconds=0.01,
        http_request=fake_http_request,
    )

    assert result["passed"] is False
    assert result["terminal_status"] == "terminal_failure"
    assert result["terminal_failure_event_count"] == 1
    assert result["failure_reason"]["error_class"] == "SEMANTIC_REJECTION"
    assert "FAIL smoke" in capsys.readouterr().out


def test_smoke_probe_timeout_reports_bounded_terminal_wait(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_http_request(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        json_body: Mapping[str, Any] | None,
    ) -> HttpResponse:
        del method, headers, json_body
        if url.endswith("/boundary/translation/ingress"):
            return _json_response(
                202,
                {"ingress_id": "ingress-smoke"},
            )
        if url.endswith("/coordination/dispatch"):
            return _json_response(
                200,
                {
                    "dispatch_id": "dispatch-smoke",
                    "session_id": "11111111-1111-1111-1111-111111111111",
                    "execution_id": "execution-smoke",
                },
            )
        if url.endswith("/session/11111111-1111-1111-1111-111111111111/timeline"):
            return _json_response(
                200,
                {
                    "events": [
                        {
                            "event_type": "diagnostic_execution_failed",
                            "payload": {
                                "error_class": "PERSISTENCE_FAILURE",
                                "retry_requested": True,
                                "retry_queue": "diagnostic.retry",
                                "retry_countdown_seconds": 15,
                            },
                        }
                    ]
                },
            )
        return _json_response(404, {"detail": {"code": "not_found"}})

    result = run_smoke_probe(
        base_url="https://example.test/api/v1",
        tenant_id="anker-pilot",
        principal_id="operator",
        bearer_token="token",
        allow_legacy_headers=False,
        external_id="s10-smoke-test",
        timeout_seconds=0.01,
        poll_interval_seconds=0.001,
        http_request=fake_http_request,
    )

    assert result["passed"] is False
    assert result["terminal_status"] == "timeout"
    assert result["retry_failure_event_count"] >= 1
    assert "did not reach terminal within 0.01s" in result["failure_reason"]["message"]
    assert "FAIL smoke" in capsys.readouterr().out


def test_probe_helpers_are_stable() -> None:
    first = s10_probe_dead_letter_id(
        tenant_id="anker-pilot",
        probe_id="probe-1",
    )
    second = s10_probe_dead_letter_id(
        tenant_id="anker-pilot",
        probe_id="probe-1",
    )

    assert first == second
    assert normalize_api_base_url("https://example.test") == (
        "https://example.test/api/v1/"
    )
    assert normalize_api_base_url("https://example.test/api/v1") == (
        "https://example.test/api/v1/"
    )


def test_s10_probe_task_routes_to_dead_letter_queue() -> None:
    routes = celery_app.conf.task_routes

    assert routes["s10_dead_letter_probe"]["queue"] == QUEUE_DEAD_LETTER
    assert getattr(s10_dead_letter_probe, "ignore_result") is True
    assert getattr(s10_dead_letter_probe, "max_retries") == 0


@pytest.mark.asyncio
async def test_workers_dlq_probe_seeds_execution_and_passes_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe_execution = {
        "execution_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "s10-execution")),
        "session_id": "s10-probe-session:probe-1",
        "dispatch_id": "s10-probe-dispatch:probe-1",
    }
    sent: dict[str, Any] = {}

    async def fake_ensure_probe_execution_row(
        *,
        database_url: str,
        tenant_id: str,
        probe_id: str,
    ) -> dict[str, str]:
        sent["ensure"] = {
            "database_url": database_url,
            "tenant_id": tenant_id,
            "probe_id": probe_id,
        }
        return probe_execution

    async def fake_read_dead_letter_row(
        *,
        database_url: str,
        tenant_id: str,
        dead_letter_task_id: str,
    ) -> dict[str, Any]:
        sent["read"] = {
            "database_url": database_url,
            "tenant_id": tenant_id,
            "dead_letter_task_id": dead_letter_task_id,
        }
        return {
            "dead_letter_task_id": dead_letter_task_id,
            "execution_id": probe_execution["execution_id"],
            "metadata": {"purpose": "s10_live_production_worker_dlq_proof"},
        }

    class _AsyncResult:
        id = "celery-task-id"

    def fake_send_task(
        name: str,
        *,
        kwargs: dict[str, Any],
        queue: str,
    ) -> _AsyncResult:
        sent["task"] = {"name": name, "kwargs": kwargs, "queue": queue}
        return _AsyncResult()

    monkeypatch.setattr(
        live_probes,
        "_ensure_probe_execution_row",
        fake_ensure_probe_execution_row,
    )
    monkeypatch.setattr(
        live_probes,
        "_read_dead_letter_row",
        fake_read_dead_letter_row,
    )
    monkeypatch.setattr(live_probes.celery_app, "send_task", fake_send_task)

    result = await live_probes.run_workers_dlq_probe(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        tenant_id="anker-pilot",
        probe_id="probe-1",
        timeout_seconds=0.1,
        poll_interval_seconds=0.01,
    )

    expected_dlq_id = s10_probe_dead_letter_id(
        tenant_id="anker-pilot",
        probe_id="probe-1",
    )
    assert result["passed"] is True
    assert sent["ensure"] == {
        "database_url": "postgresql+asyncpg://test:test@localhost/test",
        "tenant_id": "anker-pilot",
        "probe_id": "probe-1",
    }
    assert sent["task"] == {
        "name": "s10_dead_letter_probe",
        "queue": QUEUE_DEAD_LETTER,
        "kwargs": {
            "tenant_id": "anker-pilot",
            "probe_id": "probe-1",
            "enqueued_at": sent["task"]["kwargs"]["enqueued_at"],
            "execution_id": probe_execution["execution_id"],
            "session_id": probe_execution["session_id"],
        },
    }
    assert sent["read"] == {
        "database_url": "postgresql+asyncpg://test:test@localhost/test",
        "tenant_id": "anker-pilot",
        "dead_letter_task_id": str(expected_dlq_id),
    }
    assert "PASS workers_dlq" in capsys.readouterr().out


async def _seed_legacy_knowledge(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    content: str,
) -> None:
    await session.merge(TenantRow(tenant_id=_TENANT_ID))
    await session.flush()
    session.add(
        TenantKnowledgeDocumentRow(
            document_id=document_id,
            tenant_id=_TENANT_ID,
            title=_DOCUMENT_TITLE,
            content=content,
            document_type="policy",
            status="active",
            review_status="approved",
            version=1,
            uploaded_by="s10-test",
            vector_indexed_at=None,
            created_at=_NOW,
        )
    )
    session.add(
        TenantKnowledgeDocumentVersionRow(
            version_id=uuid.uuid5(uuid.NAMESPACE_URL, "s10-artifacts-version"),
            tenant_id=_TENANT_ID,
            document_id=document_id,
            version=1,
            title=_DOCUMENT_TITLE,
            content=content,
            document_type="policy",
            status="active",
            uploaded_by="s10-test",
            source_approval_id="approval-s10",
            content_sha256=_version_hash(plaintext=content),
            previous_version_sha256=None,
            created_at=_NOW,
            metadata_json={},
        )
    )
    await session.flush()


async def _load_knowledge_rows(
    session: AsyncSession,
    document_id: uuid.UUID,
) -> tuple[TenantKnowledgeDocumentRow, TenantKnowledgeDocumentVersionRow]:
    document = (
        await session.execute(
            select(TenantKnowledgeDocumentRow).where(
                TenantKnowledgeDocumentRow.document_id == document_id
            )
        )
    ).scalar_one()
    version = (
        await session.execute(
            select(TenantKnowledgeDocumentVersionRow).where(
                TenantKnowledgeDocumentVersionRow.document_id == document_id
            )
        )
    ).scalar_one()
    return document, version


async def _data_key_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(DataProtectionDataKeyRow)
        .where(DataProtectionDataKeyRow.tenant_id == _TENANT_ID)
    )
    return int(result.scalar_one())


def _data_protection(session: AsyncSession) -> DataProtectionService:
    return DataProtectionService(
        session,
        master_key_ring=MasterKeyRing(
            keys={"v1": b"s" * 32},
            active_version="v1",
        ),
    )


def _version_hash(*, plaintext: str) -> str:
    return canonical_sha256(
        {
            "tenant_id": _TENANT_ID,
            "document_id": str(_DOCUMENT_ID),
            "version": 1,
            "title": _DOCUMENT_TITLE,
            "content": plaintext,
            "document_type": "policy",
            "status": "active",
            "uploaded_by": "s10-test",
            "source_approval_id": "approval-s10",
            "metadata": {},
        }
    )


def _json_response(status_code: int, body: dict[str, Any]) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        headers={},
        body=json_bytes(body),
    )


def json_bytes(body: dict[str, Any]) -> bytes:
    return json.dumps(body).encode("utf-8")
