"""Break-control tests for PR-B3 — structured extraction.

Verified properties:
  BC-1  Schema invariant: value=None is the ONLY absence state; a
        malformed/inconsistent model response fails closed to the
        all-absent sentinel rather than raising into the pipeline.
  BC-2  Text fix: real extracted values merged into recommended_actions
        flow through to the connector/approval payload — order_id is the
        real number, never "unknown_sku" or a session-id placeholder.
  BC-3  No fallback lies anywhere in the chain: orchestration.py's
        _default_payload, repair_dispatch.py's _target_resource_from_payload,
        and the amount->cents conversion all degrade to None/honest
        fallbacks, never a fabricated string or number.
  BC-4  Money/goods always human (THE fail-closed proof): a refund action
        routes to PENDING_HUMAN_APPROVAL even with complete extraction and
        permissive tenant config; amount thresholds never auto-approve
        money/goods disbursement.
  BC-5  Live-Anthropic proofs (requires_live_anthropic):
        - text extraction returns the real order_id from plain ticket text.
        - vision extraction (B2 pattern, requires_s3) reads a synthetic
          invoice image and returns the right seller/date/amount.
        - adversarial ambiguity: two conflicting order numbers in one
          ticket never produce confidence "high" on either.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Mapping, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.agents.tools.connectors.repair_dispatch import (
    _target_resource_from_payload,  # pyright: ignore[reportPrivateUsage]
)
from app.agents.tools.orchestration import (
    _amount_to_cents,  # pyright: ignore[reportPrivateUsage]
    _default_payload,  # pyright: ignore[reportPrivateUsage]
)
from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.attachments.storage_service import AttachmentStorageService
from app.cognition.diagnostic_runtime import (
    DiagnosticCognitionRuntime,
    DiagnosticReasoningSnapshot,
    parse_diagnostic_output,
)
from app.cognition.exceptions import CognitionLLMProviderError
from app.cognition.extraction import (
    ExtractedField,
    ExtractedOrderFields,
    parse_extracted_fields,
)
from app.cognition.llm import AnthropicMessagesClient, DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMOutput
from app.core.config import Settings
from app.data_protection.crypto import DataProtectionService
from app.knowledge.models import KnowledgeRetrievalResult
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import ResolutionProposalId
from app.resolution.persistence.records import ResolutionProposalRecord
from app.runtime.resolution_autonomy_policy import ResolutionAutonomyPolicy
from app.runtime.resolution_runtime import (
    _evaluate_gate,  # pyright: ignore[reportPrivateUsage]
    _recommended_actions,  # pyright: ignore[reportPrivateUsage]
)
from app.runtime.resolution_taxonomy_policy import (
    ResolutionTaxonomyCategory,
    ResolutionTaxonomyPolicy,
)
from app.runtime.warranty_refund_eligibility import (
    _parse_date,  # pyright: ignore[reportPrivateUsage]
)
from tests._png_text_renderer import render_text_png
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

requires_s3 = pytest.mark.skipif(
    not os.environ.get("ATTACHMENTS_S3_BUCKET"),
    reason="requires ATTACHMENTS_S3_BUCKET (+ region/credentials) for the real-S3 vision break-control.",
)
requires_live_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason=(
        "requires ANTHROPIC_API_KEY for the live-model extraction break-controls — "
        "the deterministic test client never looks at ticket content, so only a "
        "real model call can prove extraction (and ambiguity-honesty) actually works."
    ),
)

TENANT_ID = "tenant-extraction-bc"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
DISPATCH_ID = "33333333-3333-4333-8333-333333333333"


def _refund_taxonomy() -> ResolutionTaxonomyPolicy:
    return ResolutionTaxonomyPolicy(
        categories=(
            ResolutionTaxonomyCategory(
                id="refund_eligible",
                label="Refund eligible",
                description="Customer is eligible for a refund.",
                recommended_actions=(
                    {
                        "type": "refund_request",
                        "tool_name": "refund.request",
                        "requires_execution": True,
                    },
                ),
            ),
        ),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )


def _proposal(*, action: Mapping[str, Any]) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=ResolutionProposalId(uuid.uuid5(uuid.NAMESPACE_URL, "b3-proposal")),
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id="44444444-4444-4444-8444-444444444444",
        proposed_customer_reply="We have reviewed your refund request.",
        resolution_category="refund_eligible",
        confidence=0.9,
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=ResolutionGovernanceVerdict.ALLOW,
        autonomy_decision=ResolutionAutonomyDecision.AUTO_APPROVED,
        status=ResolutionProposalStatus.SEND_ELIGIBLE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        recommended_actions=(action,),
    )


class _FakeKnowledgeRuntime:
    async def retrieve(
        self, *, tenant_id: str, query: str, top_k: int, max_tokens: int
    ) -> KnowledgeRetrievalResult:
        _ = (top_k, max_tokens)
        return KnowledgeRetrievalResult(
            tenant_id=tenant_id,
            query=query,
            items=(),
            citations=(),
            budget_decisions=(),
            total_tokens=0,
            vector_index_name="extraction-bc-test",
        )


class _UnusedUsagePersistence:
    pass


def _diagnostic_runtime(llm_client: Any) -> DiagnosticCognitionRuntime:
    return DiagnosticCognitionRuntime(
        knowledge_runtime=cast(Any, _FakeKnowledgeRuntime()),
        llm_client=llm_client,
        usage_persistence=cast(Any, _UnusedUsagePersistence()),
    )


async def _ensure_tenant_row(
    *,
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    tenant_id: str,
) -> None:
    from sqlalchemy import text

    statement = (
        "INSERT INTO public.tenants (tenant_id, status) "
        "VALUES (:tenant_id, 'active') ON CONFLICT (tenant_id) DO NOTHING"
    )
    if pg_seed_engine is None:
        await pg_session.execute(text(statement), {"tenant_id": tenant_id})
        await pg_session.commit()
        return
    async with pg_seed_engine.begin() as connection:
        await connection.execute(text(statement), {"tenant_id": tenant_id})


# ─── BC-1: schema invariant + fail-closed parsing ─────────────────────────


def test_extracted_field_value_none_is_only_absence_state() -> None:
    with pytest.raises(ValueError):
        ExtractedField(value=None, confidence="low")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ExtractedField(value="ORD-1", confidence=None)  # type: ignore[arg-type]
    absent = ExtractedField()
    assert absent.value is None
    assert absent.confidence is None
    assert absent.source == "none"


def test_parse_extracted_fields_fails_closed_on_malformed_input() -> None:
    # Mirrors a real observed model response: value null paired with a
    # non-null confidence — violates the invariant, must not raise into
    # the diagnostic pipeline.
    result = parse_extracted_fields({"order_id": {"value": None, "confidence": "low"}})
    assert result.order_id.value is None
    assert result.order_id.confidence is None

    assert parse_extracted_fields(None) == ExtractedOrderFields()
    assert parse_extracted_fields({"garbage": "not a schema"}) == ExtractedOrderFields()


# ─── BC-2: text fix — real values flow through, not placeholders ─────────


def test_recommended_actions_merges_real_order_id_fixes_unknown_sku() -> None:
    taxonomy = _refund_taxonomy()
    extracted = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-REAL-123", confidence="high", source="text"),
        amount=ExtractedField(value="49.99", confidence="high", source="text"),
    )
    actions = _recommended_actions("refund_eligible", taxonomy, extracted)
    assert actions[0]["order_id"] == "ORD-REAL-123"
    assert actions[0]["amount"] == "49.99"

    payload = _default_payload(
        action=actions[0],
        proposal=_proposal(action=actions[0]),
        action_type="refund_request",
        tool_name="refund.request",
    )
    assert payload["order_id"] == "ORD-REAL-123"
    assert payload["refund_amount_cents"] == 4999
    assert payload["order_id"] != "unknown_sku"
    assert not str(payload["order_id"]).startswith("session-")


def test_recommended_actions_with_no_extraction_leaves_action_unchanged() -> None:
    """Backward-compat: extracted_fields=None (the default) must not
    mutate or even copy the action dicts — existing callers/tests that
    never pass extraction keep working byte-for-byte."""
    taxonomy = _refund_taxonomy()
    actions = _recommended_actions("refund_eligible", taxonomy)
    assert actions == taxonomy.actions_for("refund_eligible")


# ─── BC-3: no fallback lies anywhere in the chain ─────────────────────────


def test_default_payload_has_no_fallback_lies_when_extraction_missing() -> None:
    action: dict[str, Any] = {"type": "refund_request", "tool_name": "refund.request"}
    payload = _default_payload(
        action=action,
        proposal=_proposal(action=action),
        action_type="refund_request",
        tool_name="refund.request",
    )
    assert payload["order_id"] is None
    assert payload["product_sku"] is None
    assert payload["refund_amount_cents"] is None
    assert payload["order_id"] != "unknown_sku"
    assert payload["refund_amount_cents"] != 5000


def test_target_resource_from_payload_no_fallback_lies() -> None:
    assert _target_resource_from_payload({}) == "repair"
    assert _target_resource_from_payload({"product_sku": "SKU-1"}) == "repair:sku:SKU-1"
    assert (
        _target_resource_from_payload({"order_id": "ORD-1", "product_sku": "SKU-1"})
        == "repair:ORD-1:SKU-1"
    )
    rendered = _target_resource_from_payload({})
    assert "unknown" not in rendered


@pytest.mark.parametrize(
    ("raw", "expected_cents"),
    [
        ("$49.99", 4999),
        ("1,234.56", 123456),
        ("49", 4900),
        (None, None),
        ("not a number", None),
    ],
)
def test_amount_to_cents_parses_or_fails_closed(
    raw: str | None, expected_cents: int | None
) -> None:
    assert _amount_to_cents(raw) == expected_cents


# ─── BC-4: honest absence blocks auto-eligibility (THE fail-closed proof) ─


def test_money_goods_commitment_is_always_human_even_with_complete_extraction() -> None:
    """A refund action must require human approval regardless of threshold,
    allowlist, or extraction completeness."""
    taxonomy = _refund_taxonomy()
    autonomy_policy = ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({"refund_eligible"}),
        monetary_commitment_threshold_cents=1_000_000,
    )
    evidence = (
        {
            "rank": 1,
            "document_id": "55555555-5555-4555-8555-555555555555",
            "title": "Refund policy",
            "document_type": "sop",
            "document_status": "active",
            "score": 0.9,
            "chunk_ordinal": 0,
            "token_count": 64,
        },
    )
    actions = _recommended_actions("refund_eligible", taxonomy, None)

    gate_missing = _evaluate_gate(
        category="refund_eligible",
        original_content="Please refund my order.",
        reply="We will process your refund.",
        evidence=evidence,
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
        recommended_actions=actions,
        extracted_fields=None,
    )
    assert gate_missing.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert gate_missing.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert "money_or_goods_commitment_requires_human_approval" in gate_missing.reasons
    assert any(
        reason.startswith("missing_required_extraction_field:refund_request:")
        for reason in gate_missing.reasons
    )

    # Even with both required fields present at sufficient confidence, the
    # SAME refund commitment must still stay human-reviewed.
    complete = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        amount=ExtractedField(value="10.00", confidence="high", source="text"),
    )
    actions_complete = _recommended_actions("refund_eligible", taxonomy, complete)
    gate_complete = _evaluate_gate(
        category="refund_eligible",
        original_content="Please refund my order.",
        reply="We will process your refund.",
        evidence=evidence,
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
        recommended_actions=actions_complete,
        extracted_fields=complete,
    )
    assert gate_complete.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert gate_complete.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert "money_or_goods_commitment_requires_human_approval" in gate_complete.reasons


def test_safe_non_money_reply_still_auto_approves_when_allowlisted() -> None:
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(
            ResolutionTaxonomyCategory(
                id="troubleshooting",
                label="Troubleshooting",
                description="Safe troubleshooting guidance.",
                recommended_actions=(
                    {
                        "type": "collect_context",
                        "tool_name": "conversation.probe",
                        "requires_execution": False,
                    },
                ),
            ),
        ),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )
    autonomy_policy = ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({"troubleshooting"}),
        monetary_commitment_threshold_cents=0,
    )
    gate = _evaluate_gate(
        category="troubleshooting",
        original_content="My device will not power on.",
        reply="Please hold the power button for 10 seconds, then try again.",
        evidence=(
            {
                "rank": 1,
                "document_id": "66666666-6666-4666-8666-666666666666",
                "title": "Troubleshooting guide",
                "document_type": "sop",
                "document_status": "active",
                "score": 0.9,
                "chunk_ordinal": 0,
                "token_count": 64,
            },
        ),
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
        recommended_actions=_recommended_actions("troubleshooting", taxonomy, None),
        extracted_fields=None,
    )

    assert gate.status is ResolutionProposalStatus.AUTO_APPROVED
    assert gate.autonomy_decision is ResolutionAutonomyDecision.AUTO_APPROVED


def test_low_confidence_extraction_also_blocks_auto_eligibility() -> None:
    """Missing is not the only fail-closed trigger — a present-but-low-
    confidence value must block exactly the same way."""
    taxonomy = _refund_taxonomy()
    autonomy_policy = ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({"refund_eligible"}),
        monetary_commitment_threshold_cents=1_000_000,
    )
    evidence = (
        {
            "rank": 1,
            "document_id": "55555555-5555-4555-8555-555555555555",
            "title": "Refund policy",
            "document_type": "sop",
            "document_status": "active",
            "score": 0.9,
            "chunk_ordinal": 0,
            "token_count": 64,
        },
    )
    low_confidence = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="low", source="text"),
        amount=ExtractedField(value="10.00", confidence="high", source="text"),
    )
    actions = _recommended_actions("refund_eligible", taxonomy, low_confidence)
    gate = _evaluate_gate(
        category="refund_eligible",
        original_content="Please refund my order.",
        reply="We will process your refund.",
        evidence=evidence,
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
        recommended_actions=actions,
        extracted_fields=low_confidence,
    )
    assert gate.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert "missing_required_extraction_field:refund_request:order_id" in gate.reasons


# ─── BC-5: live-Anthropic proofs ───────────────────────────────────────────


async def _complete_and_parse_with_retry(
    runtime: DiagnosticCognitionRuntime,
    snapshot: DiagnosticReasoningSnapshot,
) -> DiagnosticLLMOutput:
    """These live tests call complete_reasoning_snapshot + parse directly
    rather than the full persist_reasoning_result path (to avoid needing
    governance/audit/usage-persistence infra), so they don't get
    diagnostic_runtime.py's production JSON-parse self-correction retry
    for free. Mirror it here with an actual corrective prompt rather than
    a bare identical resend: at temperature=0.0 a bare resend barely
    changes the odds and can reproduce the SAME malformed output
    (confirmed live in CI — the same parse error at the same offset, two
    runs in a row) — telling the model what broke is what actually gives
    the retry a real chance, same as production."""
    completion = await runtime.complete_reasoning_snapshot(snapshot)
    try:
        return parse_diagnostic_output(completion.text)
    except CognitionLLMProviderError as exc:
        corrective_snapshot = replace(
            snapshot,
            messages=(
                *snapshot.messages,
                DiagnosticLLMMessage(role="assistant", content=completion.text),
                DiagnosticLLMMessage(
                    role="user",
                    content=(
                        "Rewrite the prior diagnostic response. It could not "
                        f"be parsed as valid JSON: {exc}. Return strictly "
                        "valid JSON only: no markdown code fences, no "
                        "commentary before or after the JSON object, and any "
                        "double quote character that appears inside a string "
                        'value must be escaped as \\".'
                    ),
                ),
            ),
        )
        corrected = await runtime.complete_reasoning_snapshot(corrective_snapshot)
        return parse_diagnostic_output(corrected.text)


@requires_live_anthropic
@pytest.mark.asyncio
async def test_live_text_extraction_returns_real_order_id() -> None:
    # A fresh httpx.AsyncClient per test, not the process-wide shared
    # client: the shared client is a module-level singleton bound to
    # whichever event loop first created it, and pytest-asyncio gives
    # each test function its own loop — reusing the shared client across
    # tests raises "Event loop is closed" on the second/third live test
    # in this file. Same shape as test_anthropic_client_circuit.py's
    # per-test http_client= pattern, just with a real transport.
    async with httpx.AsyncClient() as http_client:
        runtime = _diagnostic_runtime(
            AnthropicMessagesClient(
                api_key=Settings().ANTHROPIC_API_KEY,
                model=Settings().ANTHROPIC_DEFAULT_MODEL,
                http_client=http_client,
            )
        )
        ticket = (
            "Hi, I'd like a refund for my order. The order number is "
            "ORD-2026-77412 and I paid $89.50 for it."
        )
        snapshot = await runtime.load_reasoning_snapshot(
            tenant_id=TENANT_ID,
            execution_id="exec-text-extract",
            dispatch_id=DISPATCH_ID,
            session_id=SESSION_ID,
            content=ticket,
        )
        parsed = await _complete_and_parse_with_retry(runtime, snapshot)

    extracted = parse_extracted_fields(parsed.extracted_fields)
    assert extracted.order_id.value == "ORD-2026-77412"
    assert extracted.order_id.confidence == "high"
    assert extracted.order_id.source == "text"


@requires_live_anthropic
@requires_s3
@pytest.mark.asyncio
async def test_live_vision_extraction_reads_invoice_image(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-extract-vision-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    settings = Settings()
    blob_store = AttachmentBlobStore.from_settings(settings)
    data_protection = DataProtectionService.from_settings(pg_session, settings)
    repository = AttachmentRepository(
        pg_session, data_protection=data_protection, blob_store=blob_store
    )
    storage_service = AttachmentStorageService.from_settings(
        settings, repository=repository, blob_store=blob_store, data_protection=data_protection
    )
    png_bytes = render_text_png("ZX-77231-QD ROXX 20260115 499")
    record = await storage_service.store(
        [png_bytes], tenant_id=tenant_id, channel="email", content_type_declared="image/png"
    )
    assert record.status == "stored"

    ticket = (
        "Customer asks: 'Can you check my order using the attached invoice "
        "image?' The image shows, in order separated by spaces: the order "
        "number, the seller code, the purchase date (YYYYMMDD), and the "
        "amount in whole dollars."
    )
    try:
        async with httpx.AsyncClient() as http_client:
            runtime = DiagnosticCognitionRuntime(
                knowledge_runtime=cast(Any, _FakeKnowledgeRuntime()),
                llm_client=AnthropicMessagesClient(
                    api_key=settings.ANTHROPIC_API_KEY,
                    model=settings.ANTHROPIC_DEFAULT_MODEL,
                    http_client=http_client,
                ),
                usage_persistence=cast(Any, _UnusedUsagePersistence()),
                attachment_repository=repository,
            )
            snapshot = await runtime.load_reasoning_snapshot(
                tenant_id=tenant_id,
                execution_id="exec-vision-extract",
                dispatch_id=DISPATCH_ID,
                session_id=SESSION_ID,
                content=ticket,
                attachment_ids=(str(record.attachment_id),),
            )
            parsed = await _complete_and_parse_with_retry(runtime, snapshot)

        extracted = parse_extracted_fields(parsed.extracted_fields)
        assert extracted.order_id.value == "ZX-77231-QD"
        assert extracted.seller.value == "ROXX"
        # The model is free to emit any of W1's supported date formats
        # (e.g. "2026-01-15" vs "20260115") for the same calendar date --
        # pin the semantic date W1 eligibility will actually parse, not
        # one exact LLM-emitted string, so format non-determinism that W1
        # already tolerates doesn't flake CI.
        assert extracted.purchase_date.value is not None
        assert _parse_date(extracted.purchase_date.value) == date(2026, 1, 15)
        assert extracted.amount.value in ("499", "499.00", "$499")
        assert extracted.order_id.source == "document"
    finally:
        blob_store.delete(record.storage_key)  # type: ignore[arg-type]


@requires_live_anthropic
@pytest.mark.asyncio
async def test_live_adversarial_ambiguity_does_not_fabricate_confidence() -> None:
    """LOAD-BEARING: two genuinely conflicting order numbers in the same
    ticket must never produce confidence "high" on either — a confidently
    wrong extraction feeds a confidently wrong money decision."""
    ticket = (
        "I need a refund. My order number is ZX-11111-AA. Wait, actually, "
        "I just double-checked my email and it might be ZX-99999-BB "
        "instead — I genuinely cannot tell which one is correct, they're "
        "both in my inbox and I'm confused about which order this is."
    )
    async with httpx.AsyncClient() as http_client:
        runtime = _diagnostic_runtime(
            AnthropicMessagesClient(
                api_key=Settings().ANTHROPIC_API_KEY,
                model=Settings().ANTHROPIC_DEFAULT_MODEL,
                http_client=http_client,
            )
        )
        snapshot = await runtime.load_reasoning_snapshot(
            tenant_id=TENANT_ID,
            execution_id="exec-ambiguous",
            dispatch_id=DISPATCH_ID,
            session_id=SESSION_ID,
            content=ticket,
        )
        parsed = await _complete_and_parse_with_retry(runtime, snapshot)

    extracted = parse_extracted_fields(parsed.extracted_fields)

    confidently_wrong = (
        extracted.order_id.value is not None
        and extracted.order_id.confidence == "high"
    )
    assert not confidently_wrong, (
        "model confidently picked one of two conflicting order numbers: "
        f"{extracted.order_id!r}"
    )
