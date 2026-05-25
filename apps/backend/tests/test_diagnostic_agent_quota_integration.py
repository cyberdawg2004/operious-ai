from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import pytest

from app.agents.runtime.quota_runtime import TenantQuotaRuntime
from app.cognition.diagnostic_runtime import DiagnosticCognitionRuntime
from app.cognition.exceptions import ProviderQuotaExceededError
from app.cognition.llm import DiagnosticLLMMessage
from app.knowledge.models import KnowledgeRetrievalResult


class _FakeKnowledgeRuntime:
    async def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        max_tokens: int,
    ) -> KnowledgeRetrievalResult:
        _ = (top_k, max_tokens)
        return KnowledgeRetrievalResult(
            tenant_id=tenant_id,
            query=query,
            items=(),
            citations=(),
            budget_decisions=(),
            total_tokens=0,
            vector_index_name="quota-test",
        )


class _UnexpectedLLMClient:
    provider_name = "provider-test"
    model_name = "model-test"

    def __init__(self) -> None:
        self.called = False

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> object:
        _ = (system_prompt, messages, max_output_tokens, temperature, tenant_id)
        self.called = True
        raise AssertionError("LLM client should not be called when quota blocks")


class _BlockingQuotaRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def check_and_increment(
        self,
        tenant_id: str,
        provider: str,
        model: str,
    ) -> None:
        self.calls.append((tenant_id, provider, model))
        raise ProviderQuotaExceededError(
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            quota_type="requests_per_minute",
            retry_after_seconds=90,
        )


class _UnusedUsagePersistence:
    pass


@pytest.mark.asyncio
async def test_quota_check_runs_before_llm_call() -> None:
    quota_runtime = _BlockingQuotaRuntime()
    llm_client = _UnexpectedLLMClient()
    runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=cast(Any, _FakeKnowledgeRuntime()),
        llm_client=cast(Any, llm_client),
        usage_persistence=cast(Any, _UnusedUsagePersistence()),
        quota_runtime=cast(TenantQuotaRuntime, quota_runtime),
    )

    with pytest.raises(ProviderQuotaExceededError):
        await runtime.reason_about_ticket(
            tenant_id="tenant-quota",
            execution_id="execution-quota",
            dispatch_id="dispatch-quota",
            session_id="session-quota",
            content="Charging issue",
            attempt_id="attempt-quota",
        )

    assert quota_runtime.calls == [
        ("tenant-quota", "provider-test", "model-test")
    ]
    assert llm_client.called is False
