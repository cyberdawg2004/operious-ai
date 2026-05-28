from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.agents.runtime.quota_runtime import TenantQuotaRuntime
from app.api.v1.schemas.ingress.batch import max_batch_size
from app.cognition.exceptions import ProviderRateLimitError
from app.db.session import get_owner_session_factory, get_session_factory
from app.db.tenant_context import set_current_tenant
from app.dependencies.services import (
    check_batch_ingest_admission,
    get_execution_publisher,
)
from app.hardening.admission.models import AdmissionReason
from app.workers.agent_tasks import execute_diagnostic_agent_runtime
from tests.conftest import requires_postgres


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.chaos
async def test_provider_429_direct_runtime_dead_letters(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "chaos-429-tenant"
    await committed_burst_seed["seed_tenant"](tenant_id)
    execution_id = await committed_burst_seed["seed_execution"](tenant_id)

    async def raise_429(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise ProviderRateLimitError(
            "rate limited",
            retry_after_seconds=30,
        )

    from app.agents.runtime import quota_runtime as quota_module

    monkeypatch.setattr(quota_module, "_quota_runtime", None)
    monkeypatch.setattr(
        "app.cognition.llm.DeterministicDiagnosticLLMClient.complete",
        raise_429,
    )
    monkeypatch.setattr(
        "app.cognition.semantic.validate_governance_terms",
        lambda **kwargs: kwargs,
    )

    set_current_tenant(tenant_id)
    result = await execute_diagnostic_agent_runtime(
        execution_id=execution_id,
        tenant_id=tenant_id,
    )

    assert result["status"] == "dead_lettered"
    assert result["error_class"] in ("PROVIDER_429", "PROVIDER_RATE_LIMIT")
    assert result["attempt_count"] == 1

    async with get_owner_session_factory()() as session:
        dlq = await session.execute(
            text(
                """
                SELECT COUNT(*), MAX(metadata->>'error_class')
                FROM dead_letter_tasks
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        )
        dlq_count, dlq_error_class = dlq.one()
        decisions = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM governance_decisions
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        )

    assert dlq_count == 1
    assert dlq_error_class in ("PROVIDER_429", "PROVIDER_RATE_LIMIT")
    assert decisions.scalar_one() == 0


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.chaos
async def test_duplicate_webhook_returns_200_no_new_ingress(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    chaos_email_channel_seed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "chaos-duplicate-webhook-tenant"
    routing_address = "duplicate-chaos@example.com"
    secret = "email-secret"
    nonce = "duplicate-webhook-message"
    await chaos_email_channel_seed(tenant_id, routing_address, secret)
    monkeypatch.setattr(
        "app.dependencies.services.get_redis_client",
        lambda: _HealthyAdmissionRedis(),
    )

    from app.main import create_app

    app = create_app()
    body = _email_webhook_body(
        routing_address=routing_address,
        nonce=nonce,
        timestamp=datetime.now(timezone.utc),
    )
    raw_body = _raw_json(body)
    headers = {
        "content-type": "application/json",
        "X-Tenant-ID": tenant_id,
        **_email_signature_headers(secret=secret, raw_body=raw_body),
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/api/v1/boundary/translation/channels/email/webhook",
            content=raw_body,
            headers=headers,
        )
        second = await client.post(
            "/api/v1/boundary/translation/channels/email/webhook",
            content=raw_body,
            headers=headers,
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    async with get_owner_session_factory()() as session:
        count = await _count_boundary_records(
            session=session,
            tenant_id=tenant_id,
            external_message_id=nonce,
        )

    assert count == 1


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.chaos
async def test_stale_webhook_signature_rejected_before_ingress(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    chaos_email_channel_seed,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "chaos-stale-webhook-tenant"
    routing_address = "stale-chaos@example.com"
    secret = "email-secret"
    nonce = "stale-webhook-message"
    await chaos_email_channel_seed(tenant_id, routing_address, secret)

    from app.main import create_app

    app = create_app()
    body = _email_webhook_body(
        routing_address=routing_address,
        nonce=nonce,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    raw_body = _raw_json(body)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/boundary/translation/channels/email/webhook",
            content=raw_body,
            headers={
                "content-type": "application/json",
                "X-Tenant-ID": tenant_id,
                **_email_signature_headers(secret=secret, raw_body=raw_body),
            },
        )

    assert response.status_code == 401, response.text
    async with get_owner_session_factory()() as session:
        count = await _count_boundary_records(
            session=session,
            tenant_id=tenant_id,
            external_message_id=nonce,
        )
    assert count == 0


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.chaos
async def test_partial_batch_valid_committed_invalid_rejected(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "chaos-partial-batch-tenant"
    await committed_burst_seed["seed_tenant"](tenant_id)

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_execution_publisher] = _NoOpExecutionPublisher
    app.dependency_overrides[check_batch_ingest_admission] = _admitted

    items = [
        _batch_item("partial-valid", index)
        for index in range(7)
    ]
    items.extend(
        _batch_item("partial-invalid", index, body="")
        for index in range(3)
    )
    assert len(items) <= max_batch_size()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/ingest/batch",
            json={"items": items},
            headers={"X-Tenant-ID": tenant_id},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["accepted"] == 7
    assert payload["rejected"] == 3
    assert payload["duplicate"] == 0

    async with get_owner_session_factory()() as session:
        valid_records = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM boundary_ingress
                WHERE tenant_id = :tenant_id
                  AND external_message_id LIKE 'partial-valid-%'
                """
            ),
            {"tenant_id": tenant_id},
        )
        invalid_records = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM boundary_ingress
                WHERE tenant_id = :tenant_id
                  AND external_message_id LIKE 'partial-invalid-%'
                """
            ),
            {"tenant_id": tenant_id},
        )
    assert valid_records.scalar_one() == 7
    assert invalid_records.scalar_one() == 0


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.chaos
async def test_worker_restart_does_not_duplicate_execution(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "chaos-worker-restart-tenant"
    await committed_burst_seed["seed_tenant"](tenant_id)
    execution_id = await committed_burst_seed["seed_execution"](tenant_id)

    from app.agents.runtime import quota_runtime as quota_module

    monkeypatch.setattr(quota_module, "_quota_runtime", None)
    set_current_tenant(tenant_id)
    first = await execute_diagnostic_agent_runtime(
        execution_id=execution_id,
        tenant_id=tenant_id,
    )
    second = await execute_diagnostic_agent_runtime(
        execution_id=execution_id,
        tenant_id=tenant_id,
    )

    assert first["status"] == "completed", first
    assert second["status"] in {"claim_refused", "completed"}, second

    async with get_owner_session_factory()() as session:
        decision_count = await session.execute(
            text(
                """
                SELECT policy_chain_id, COUNT(*)
                FROM governance_decisions
                WHERE tenant_id = :tenant_id
                GROUP BY policy_chain_id
                """
            ),
            {"tenant_id": tenant_id},
        )
        event_counts = await session.execute(
            text(
                """
                SELECT COUNT(*), COUNT(DISTINCT sequence)
                FROM session_events
                WHERE session_id = (
                    SELECT CAST(session_id AS uuid)
                    FROM execution_records
                    WHERE execution_id = CAST(:execution_id AS uuid)
                )
                """
            ),
            {"execution_id": execution_id},
        )
        audit_count = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM cognition_audit_records
                WHERE tenant_id = :tenant_id
                  AND execution_id = :execution_id
                """
            ),
            {"tenant_id": tenant_id, "execution_id": execution_id},
        )

    total_events, distinct_sequences = event_counts.one()
    assert dict(decision_count.all()) == {
        "cognition.llm_diagnostic.pre_execution": 1,
        "resolution.communication.pre_execution": 1,
    }
    assert total_events == distinct_sequences
    assert audit_count.scalar_one() == 1


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.chaos
async def test_processing_continues_when_redis_unavailable(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "chaos-redis-unavailable-tenant"
    await committed_burst_seed["seed_tenant"](tenant_id)
    execution_id = await committed_burst_seed["seed_execution"](tenant_id)

    from app.agents.runtime import quota_runtime as quota_module

    quota_runtime = TenantQuotaRuntime(
        redis_url="redis://unavailable",
        session_factory=get_owner_session_factory(),
        redis_client=_UnavailableRedis(),
        request_per_minute_limit=100_000,
        tokens_per_minute_limit=100_000,
        requests_per_hour_limit=100_000,
    )
    monkeypatch.setattr(quota_module, "_quota_runtime", quota_runtime)

    set_current_tenant(tenant_id)
    result = await execute_diagnostic_agent_runtime(
        execution_id=execution_id,
        tenant_id=tenant_id,
    )

    assert result["status"] == "completed", result
    async with get_owner_session_factory()() as session:
        decisions = await session.execute(
            text(
                """
                SELECT policy_chain_id, COUNT(*)
                FROM governance_decisions
                WHERE tenant_id = :tenant_id
                GROUP BY policy_chain_id
                """
            ),
            {"tenant_id": tenant_id},
        )
    assert dict(decisions.all()) == {
        "cognition.llm_diagnostic.pre_execution": 1,
        "resolution.communication.pre_execution": 1,
    }


def _email_webhook_body(
    *,
    routing_address: str,
    nonce: str,
    timestamp: datetime,
) -> dict[str, object]:
    return {
        "message_id": nonce,
        "nonce": nonce,
        "to": routing_address,
        "text": "customer reports device charging failure",
        "timestamp": timestamp.isoformat(),
    }


def _email_signature_headers(
    *,
    secret: str,
    raw_body: bytes,
) -> dict[str, str]:
    digest = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {"X-Operious-Signature": f"sha256={digest}"}


def _raw_json(body: dict[str, object]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _batch_item(prefix: str, index: int, *, body: str | None = None) -> dict[str, object]:
    return {
        "channel_type": "email",
        "source_id": "chaos-batch-source",
        "external_message_id": f"{prefix}-{index}",
        "subject": "Chaos batch ticket",
        "body": "customer needs help" if body is None else body,
        "received_at": "2026-05-25T12:00:00+00:00",
        "metadata": {"origin": "chaos_partial_batch", "index": index},
    }


async def _count_boundary_records(
    *,
    session: Any,
    tenant_id: str,
    external_message_id: str,
) -> int:
    result = await session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM boundary_ingress
            WHERE tenant_id = :tenant_id
              AND external_message_id = :external_message_id
            """
        ),
        {
            "tenant_id": tenant_id,
            "external_message_id": external_message_id,
        },
    )
    return int(result.scalar_one())


async def _admitted() -> object:
    return object()


class _NoOpExecutionPublisher:
    async def publish_execution(
        self,
        execution_id: str,
        *,
        tenant_id: str,
    ) -> None:
        del execution_id, tenant_id


class _HealthyAdmissionRedis:
    def info(self, section: str | None = None) -> dict[str, int]:
        del section
        return {"used_memory": 0, "maxmemory": 0}

    def llen(self, name: str) -> int:
        del name
        return 0

    def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[object]:
        del name, start, end, withscores
        return []


class _UnavailableRedis:
    def pipeline(self) -> object:
        raise ConnectionError("redis unavailable")

    async def get(self, key: str) -> object | None:
        del key
        raise ConnectionError("redis unavailable")

    async def aclose(self) -> None:
        return None
