from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import pytest

from app.cognition import DiagnosticCognitionRuntime, DiagnosticCognitionRuntimeConfig
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.persistence import InMemoryCognitionUsagePersistence
from app.knowledge.models import KnowledgeRetrievalResult
from app.runtime.conversation_generation import (
    ConversationGenerationRequest,
    GroundedConversationGenerationRuntime,
)


@dataclass
class _CapturingKnowledgeRuntime:
    query: str | None = None

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        max_tokens: int,
    ) -> KnowledgeRetrievalResult:
        del tenant_id, top_k, max_tokens
        self.query = query
        return KnowledgeRetrievalResult(
            tenant_id="tenant-follow-up",
            query=query,
            items=(),
            citations=(),
            budget_decisions=(),
            total_tokens=0,
            vector_index_name="memory",
        )


@dataclass
class _NoopDiagnosticLLMClient:
    provider_name: str = "anthropic"
    model_name: str = "claude-sonnet-4-6"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> object:
        del system_prompt, messages, max_output_tokens, temperature, tenant_id
        raise AssertionError("load_reasoning_snapshot must not call complete()")


@pytest.mark.asyncio
async def test_follow_up_snapshot_threads_recent_history_into_query_and_prompt() -> (
    None
):
    knowledge = _CapturingKnowledgeRuntime()
    runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=knowledge,
        llm_client=_NoopDiagnosticLLMClient(),
        usage_persistence=InMemoryCognitionUsagePersistence(),
        config=DiagnosticCognitionRuntimeConfig(context_top_k=3),
    )

    snapshot = await runtime.load_reasoning_snapshot(
        tenant_id="tenant-follow-up",
        execution_id="11111111-1111-4111-8111-111111111111",
        dispatch_id="22222222-2222-4222-8222-222222222222",
        session_id="33333333-3333-4333-8333-333333333333",
        content="I tried those steps and it still will not charge.",
        conversation_history=(
            {"role": "customer", "content": "My PowerCore 737 will not charge."},
            {
                "role": "assistant",
                "content": "Please try another charger, another cable, and a reset.",
            },
        ),
    )

    assert knowledge.query is not None
    assert "PowerCore 737" in knowledge.query
    assert "another charger" in knowledge.query
    user_prompt = snapshot.messages[0].content
    assert isinstance(user_prompt, str)
    assert "recent_conversation_history:" in user_prompt
    assert "assistant: Please try another charger" in user_prompt


@dataclass
class _CapturingGenerationLLMClient:
    system_prompt: str | None = None
    user_prompt: str | None = None

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[object, ...],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> object:
        del max_output_tokens, temperature, tenant_id
        self.system_prompt = system_prompt
        self.user_prompt = str(getattr(messages[0], "content", ""))
        return type(
            "Completion",
            (),
            {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "text": (
                    '{"language":"en","segments":['
                    '{"kind":"acknowledgment","text":"Thanks for the update.","citation_ranks":[]},'
                    '{"kind":"question","text":"What is your order number?","citation_ranks":[]}'
                    "]}"
                ),
            },
        )()


@pytest.mark.asyncio
async def test_generation_prompt_explicitly_advances_stage_from_sop_and_history() -> (
    None
):
    llm = _CapturingGenerationLLMClient()
    runtime = GroundedConversationGenerationRuntime(llm_client=llm)

    await runtime.generate_reply(
        ConversationGenerationRequest(
            tenant_id="tenant-follow-up",
            session_id="44444444-4444-4444-8444-444444444444",
            diagnostic_summary="Customer exhausted troubleshooting for a charging issue.",
            diagnostic_category="charging_issue",
            diagnostic_confidence=0.91,
            original_content="I already tried all ports, four cables, and a full recharge.",
            source_language="en",
            evidence=(
                cast(
                    Mapping[str, Any],
                    {
                        "rank": 1,
                        "title": "Customer Response Playbook",
                        "safe_excerpt": (
                            "When troubleshooting is exhausted, move to the next "
                            "tenant-defined eligibility or handoff step."
                        ),
                    },
                ),
            ),
            conversation_history=(
                {"role": "assistant", "content": "Please try another cable and reset."},
                {"role": "customer", "content": "I already tried that."},
            ),
        )
    )

    assert llm.system_prompt is not None
    assert "do not restart the same troubleshooting loop" in llm.system_prompt
    assert "Stage transitions must come from the evidence" in llm.system_prompt
    assert llm.user_prompt is not None
    assert "conversation_history" in llm.user_prompt
