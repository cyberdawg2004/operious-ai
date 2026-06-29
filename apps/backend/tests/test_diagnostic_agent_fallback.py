from __future__ import annotations

import pytest

from app.agents.diagnostic_agent import DiagnosticAgent

TENANT_ID = "tenant-fallback-test"


@pytest.mark.asyncio
async def test_fallback_classifies_generic_charging_vocabulary() -> None:
    """The local heuristic fallback (no cognition_runtime supplied) must
    still classify ordinary charging-related text -- de-Ankering it must
    not break the legacy/offline construction path."""
    agent = DiagnosticAgent()

    result = await agent.execute(
        dispatch_id="dispatch-1",
        session_id="session-1",
        tenant_id=TENANT_ID,
        content="My battery won't charge and the charger feels warm.",
    )

    assert result.category == "charging_issue"


@pytest.mark.asyncio
async def test_fallback_has_no_anker_specific_vocabulary() -> None:
    """Domain-leak hardening: a bare product-line name with NONE of the
    generic charging vocabulary must not match charging_issue -- the
    fallback must be domain-neutral, not keyed on any tenant's specific
    product names."""
    agent = DiagnosticAgent()

    result = await agent.execute(
        dispatch_id="dispatch-2",
        session_id="session-2",
        tenant_id=TENANT_ID,
        content="My PowerCore is acting up.",
    )

    assert result.category != "charging_issue"
    assert result.category == "unknown_issue"


@pytest.mark.asyncio
async def test_fallback_classifies_a_bank_style_account_issue() -> None:
    """The bank/telecom test: the fallback's other branches were already
    domain-neutral -- confirm a non-retail tenant's account-style ticket
    classifies correctly with no electronics-specific vocabulary at all."""
    agent = DiagnosticAgent()

    result = await agent.execute(
        dispatch_id="dispatch-3",
        session_id="session-3",
        tenant_id=TENANT_ID,
        content="I can't log in to my account and my last invoice looks wrong.",
    )

    assert result.category == "account_issue"
