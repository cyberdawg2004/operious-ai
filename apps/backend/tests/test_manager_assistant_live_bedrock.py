"""Live LLM verification tests for the Manager Assistant.

Exercises the full pipeline end-to-end: natural-language question →
intent mapping → real data query → narrated answer.

The platform's LLM path is determined by LLM_PROVIDER (config.py):
  - LLM_PROVIDER=anthropic (default): direct Anthropic API via ANTHROPIC_API_KEY
  - LLM_PROVIDER=bedrock: AWS Bedrock via boto3 (LLM_AWS_REGION + AWS credentials)

Skip logic mirrors the actual credential requirements of build_llm_client():
  * Anthropic path (default): requires ANTHROPIC_API_KEY
  * Bedrock path: requires LLM_AWS_REGION (boto3 resolves AWS creds via its
    standard chain — env vars, ~/.aws/credentials, IAM role; NOT
    AWS_BEARER_TOKEN_BEDROCK which is a Claude Code SDK mechanism and is NOT
    consumed by boto3)
  * Both paths require TEST_DATABASE_URL for the ephemeral tenant DB fixture

These tests use a real (ephemeral) database tenant with seeded data.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio

_HAS_DB = bool(os.environ.get("TEST_DATABASE_URL"))

# Determine which LLM provider path will be used (mirrors build_llm_client logic).
_llm_provider = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().casefold()
if _llm_provider == "bedrock":
    # Bedrock path: needs LLM_AWS_REGION; boto3 resolves AWS creds from its
    # own chain (AWS_ACCESS_KEY_ID/SECRET, ~/.aws/credentials, or IAM role).
    _HAS_LLM = bool(os.environ.get("LLM_AWS_REGION") or os.environ.get("AWS_REGION"))
    _SKIP_REASON = (
        "requires TEST_DATABASE_URL and LLM_AWS_REGION (plus AWS credentials "
        "in the standard boto3 chain: AWS_ACCESS_KEY_ID/SECRET or ~/.aws/credentials)"
    )
else:
    # Anthropic path (default): needs ANTHROPIC_API_KEY.
    _HAS_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
    _SKIP_REASON = (
        "requires TEST_DATABASE_URL and ANTHROPIC_API_KEY "
        "(or set LLM_PROVIDER=bedrock with LLM_AWS_REGION + AWS credentials)"
    )

_SHOULD_RUN = _HAS_DB and _HAS_LLM

pytestmark = pytest.mark.skipif(not _SHOULD_RUN, reason=_SKIP_REASON)


@pytest.fixture(scope="module")
def tenant_id() -> str:
    return f"live-test-assistant-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture(scope="function")
async def live_service(tenant_id: str) -> Any:
    """Build a real ManagerAssistantService against the test DB and Bedrock."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings
    from app.cognition.llm_factory import build_llm_client
    from app.agents.governed.manager_assistant import ManagerAssistantAgent
    from app.services.manager_assistant_service import (
        ManagerAssistantService,
        ManagerQueryRunner,
    )
    from app.agents.tools.approvals import PostgresActionApprovalRepository
    from app.approvals.persistence import PostgresCaseApprovalPersistence
    from app.escalation.persistence import PostgresEscalationPersistence
    from app.observability.persistence import PostgresOperationalObservabilityPersistence
    from app.session.persistence import PostgresSessionPersistence
    from app.tenant.persistence import (
        PostgresTenantConfigurationRepository,
        TenantGovernancePolicyRecord,
    )
    from app.tenant.enums import TenantGovernancePolicyStatus
    from app.tenant.identity import derive_governance_policy_version_id
    from app.tenant.chronology import canonical_sha256
    from app.agents.governed.manager_assistant import MANAGER_ASSISTANT_POLICY_TYPE

    settings = get_settings()
    engine = create_async_engine(
        os.environ["TEST_DATABASE_URL"],
        echo=False,
        pool_size=2,
        max_overflow=2,
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        tenant_config_repo = PostgresTenantConfigurationRepository(session)

        # Seed the agent policy for our ephemeral tenant
        now = datetime.now(timezone.utc)
        params = {
            "role_description": (
                "You are an operations analytics assistant for a tenant manager. "
                "Answer questions about the manager's operation using the provided data. "
                "Be concise and factual."
            )
        }
        content_sha256 = canonical_sha256({
            "tenant_id": tenant_id,
            "policy_type": MANAGER_ASSISTANT_POLICY_TYPE,
            "parameters": params,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": "live-test",
            "effective_from": now.isoformat(),
            "source_approval_id": "live-test-approval",
        })
        policy_id = derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=MANAGER_ASSISTANT_POLICY_TYPE,
            version=1,
        )
        record = TenantGovernancePolicyRecord(
            policy_id=policy_id,
            tenant_id=tenant_id,
            policy_type=MANAGER_ASSISTANT_POLICY_TYPE,
            parameters=params,
            status=TenantGovernancePolicyStatus.ACTIVE,
            version=1,
            approved_by="live-test",
            effective_from=now,
            created_at=now,
            source_approval_id="live-test-approval",
            content_sha256=content_sha256,
            previous_version_sha256=None,
        )
        await tenant_config_repo.save_governance_policy(
            record, expected_tenant_id=tenant_id
        )
        await session.commit()

        llm_client = build_llm_client(settings)
        agent = ManagerAssistantAgent(
            llm_client=llm_client,
            tenant_configuration_repository=tenant_config_repo,
        )
        runner = ManagerQueryRunner(
            observability_persistence=PostgresOperationalObservabilityPersistence(session),
            escalation_persistence=PostgresEscalationPersistence(session),
            case_approval_persistence=PostgresCaseApprovalPersistence(session),
            action_approval_persistence=PostgresActionApprovalRepository(session),
            session_persistence=PostgresSessionPersistence(session),
            tenant_config_repo=tenant_config_repo,
        )
        service = ManagerAssistantService(agent=agent, query_runner=runner)

    yield service

    await engine.dispose()


@pytest.mark.asyncio
async def test_live_auto_resolution_rate(live_service: Any, tenant_id: str) -> None:
    """'auto-resolution rate this week' → maps to auto_resolution_rate → real data."""
    answer = await live_service.answer(
        question="What's my auto-resolution rate this week?",
        tenant_id=tenant_id,
    )
    # Should map to the correct query key
    assert answer.query_key in ("auto_resolution_rate", ""), (
        f"Unexpected query_key: {answer.query_key!r}"
    )
    if not answer.cannot_answer:
        assert answer.query_key == "auto_resolution_rate"
        assert isinstance(answer.answer, str) and len(answer.answer) > 10
        # Answer should not contain hallucinated numbers that contradict data
        print(f"\n[LIVE] auto_resolution_rate answer: {answer.answer}")
        print(f"[LIVE] chart_type={answer.chart_type} chart_data={answer.chart_data}")


@pytest.mark.asyncio
async def test_live_pending_approvals(live_service: Any, tenant_id: str) -> None:
    """'how many refunds pending approval' → maps to pending_action_approvals."""
    answer = await live_service.answer(
        question="How many refunds are pending approval?",
        tenant_id=tenant_id,
    )
    if not answer.cannot_answer:
        assert answer.query_key in (
            "pending_action_approvals",
            "pending_case_approvals",
        ), f"Got query_key={answer.query_key!r}"
        print(f"\n[LIVE] pending_approvals answer: {answer.answer}")


@pytest.mark.asyncio
async def test_live_sop_conflicts(live_service: Any, tenant_id: str) -> None:
    """'which SOPs conflict' → maps to sop_conflicts → returns conflicts (may be 0)."""
    answer = await live_service.answer(
        question="Which SOPs conflict in my knowledge base?",
        tenant_id=tenant_id,
    )
    if not answer.cannot_answer:
        assert answer.query_key == "sop_conflicts", (
            f"Expected sop_conflicts, got {answer.query_key!r}"
        )
        print(f"\n[LIVE] sop_conflicts answer: {answer.answer}")


@pytest.mark.asyncio
async def test_live_unanswerable_question(live_service: Any, tenant_id: str) -> None:
    """An out-of-scope question → honest refusal, no fabricated metric."""
    answer = await live_service.answer(
        question="What will the weather be like in Paris next Tuesday?",
        tenant_id=tenant_id,
    )
    assert answer.cannot_answer is True, (
        f"Expected cannot_answer=True for out-of-scope question, "
        f"got query_key={answer.query_key!r} answer={answer.answer!r}"
    )
    # Should NOT contain a fabricated number like "72°F" etc.
    assert "°" not in answer.answer
    print(f"\n[LIVE] unanswerable refusal: {answer.answer[:200]}")


@pytest.mark.asyncio
async def test_live_escalation_rate(live_service: Any, tenant_id: str) -> None:
    """'escalation rate this month' → maps to escalation_rate."""
    answer = await live_service.answer(
        question="What's the escalation rate this month?",
        tenant_id=tenant_id,
    )
    if not answer.cannot_answer:
        assert answer.query_key == "escalation_rate"
        print(f"\n[LIVE] escalation_rate answer: {answer.answer}")
