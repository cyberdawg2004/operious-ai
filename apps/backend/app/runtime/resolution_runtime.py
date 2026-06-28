"""Application-layer runtime for autonomous resolution proposals."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable, Mapping, Protocol, Sequence, cast

from app.boundary.translation import (
    CANONICAL_LANGUAGE,
    EgressLocalizeRequest,
    LocalizationContext,
    TranslationPayload,
    TranslationRuntime,
    derive_formality,
)
from app.cognition.extraction import (
    EXTRACTED_ORDER_FIELD_NAMES,
    ExtractedField,
    ExtractedOrderFields,
)
from app.governance.capability import OperationalAct
from app.identity import AuthorityContext, TenantId
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    ResolutionProposalId,
    derive_resolution_outbound_draft_id,
    derive_resolution_proposal_id,
)
from app.resolution.persistence import (
    ResolutionOutboundDraftPersistenceProtocol,
    ResolutionOutboundDraftRecord,
    ResolutionProposalPersistenceProtocol,
    ResolutionProposalRecord,
)
from app.runtime.conversation_generation import (
    ConversationGenerationRequest,
    ConversationGenerationRuntimeProtocol,
    GroundedConversationGenerationRuntime,
    GroundedReplyDraft,
    GroundedReplySegment,
    render_grounded_reply,
)
from app.runtime.money_goods_commitment import money_or_goods_commitment_kinds
from app.runtime.resolution_autonomy_policy import (
    ResolutionAutonomyPolicy,
    resolve_resolution_autonomy_policy,
)
from app.runtime.resolution_taxonomy_policy import (
    ResolutionTaxonomyPolicy,
    UNCLASSIFIED_CATEGORY_ID,
    resolve_resolution_taxonomy_policy,
)
from app.runtime.inventory_availability import InventoryAvailabilityChecker
from app.runtime.warranty_refund_eligibility import (
    EligibilityDetermination,
    EligibilityVerdict,
    determine_eligibility,
)
from app.runtime.warranty_refund_policy import (
    WarrantyRefundPolicy,
    resolve_warranty_refund_policy,
)
from app.runtime.warranty_refund_remedy_selection import select_available_remedy
from app.tenant.persistence import TenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from app.tenant.template_placeholders import substitute_placeholders

_DEFAULT_AUTO_APPROVE_THRESHOLD = 0.80
_DIAGNOSTIC_EVENT_TYPE = "diagnostic_analysis_completed"

_SAFETY_KEYWORDS = frozenset(
    {
        "fire",
        "smoke",
        "burn",
        "burning",
        "injury",
        "injured",
        "shock",
        "explosion",
        "exploded",
        "overheat",
        "overheating",
        "chemical",
        "fumes",
    }
)

# Broad physical-hazard signals for the worker-level safety floor.
# Every hit creates a P0/CRISIS escalation record regardless of proposal status
# or LLM category classification (Option A: reply sends if governance allows,
# escalation is created independently via the post-proposal pipeline).
# All existing _SAFETY_KEYWORDS are included so the floor fires for blocking
# cases too.  False positives are explicitly accepted — a missed safety case
# is not.
_SAFETY_FLOOR_KEYWORDS = frozenset(
    {
        "swollen",
        "bloated",
        "bulging",
        "puffy",
        "expanded",
        "leaking",
        "leak",
        "hot",
        "smoke",
        "smoking",
        "fire",
        "flame",
        "flames",
        "burn",
        "burning",
        "burns",
        "burnt",
        "spark",
        "sparks",
        "sparking",
        "melt",
        "melting",
        "melted",
        "explode",
        "exploded",
        "exploding",
        "explosion",
        "overheat",
        "overheating",
        "injury",
        "injured",
        "injuries",
        "shock",
        "chemical",
        "fumes",
    }
)


def resolution_contains_safety_floor_keywords(text: str) -> bool:
    """Return True if text contains any safety-floor keyword.

    Used by the worker to trigger a P0/CRISIS safety escalation
    independently of the proposal status and LLM category assignment.
    """
    return _contains_any(text.lower(), _SAFETY_FLOOR_KEYWORDS)
_LEGAL_KEYWORDS = frozenset(
    {
        "lawsuit",
        "lawyer",
        "attorney",
        "i will sue",
        "going to sue",
        "plan to sue",
        "sue your company",
        "legal action",
        "class action",
        "regulator",
        "chargeback",
    }
)
_FRAUD_KEYWORDS = frozenset(
    {
        "fraud",
        "stolen",
        "identity theft",
        "unauthorized purchase",
        "scam",
        "counterfeit",
    }
)
_POLICY_EXCEPTION_KEYWORDS = frozenset(
    {
        "exception",
        "override",
        "outside policy",
        "bend the rules",
        "special case",
    }
)
_BASELINE_UNSUPPORTED_PROMISE_PATTERNS = frozenset(
    {
        "we will refund",
        "we'll refund",
        "you are eligible for a refund",
        "approved for refund",
        "we will replace",
        "we'll replace",
        "approved for replacement",
        "guaranteed replacement",
    }
)
# "covered under warranty" / "warranty covers" are uniquely two-sided: they
# read as a PERSONAL commitment in "your item is covered under warranty"
# but as a GENERAL policy explanation in "Anker's warranty covers quality-
# related defects" -- a bare substring match (like every other baseline
# phrase above, which already inherently imply a personal commitment)
# can't tell them apart, so a pure-inquiry answer that explains coverage
# in the abstract was wrongly hard-denied as an unsupported promise. These
# two phrases alone get a personal-context-aware regex instead: only a
# commitment when a personal/case marker (you/your/this order/this item/
# this claim/this case) appears near the phrase.
_PERSONAL_WARRANTY_COVERAGE_PATTERN = re.compile(
    r"\b(?:you(?:'re| are)?|your|this (?:order|item|unit|device|product|"
    r"claim|case))\b.{0,60}\b(?:covered under warranty|warranty covers)\b"
    r"|"
    r"\b(?:covered under warranty|warranty covers)\b.{0,60}\b"
    r"(?:you(?:'re| are)?|your)\b",
    re.IGNORECASE,
)
_OPTIONAL_EVIDENCE_TEXT_FIELDS = (
    "chunk_id",
    "vector_id",
    "vector_index_name",
    "safe_excerpt",
    "safe_excerpt_sha256",
    "chunk_content_hash",
    "document_review_status",
)
_OPTIONAL_EVIDENCE_INT_FIELDS = (
    "citation_schema_version",
    "document_version",
    "char_start",
    "char_end",
)


@dataclass(frozen=True, slots=True)
class ResolutionProposalRequest:
    """Inputs available at diagnostic completion time."""

    tenant_id: str
    session_id: str
    execution_id: str
    dispatch_id: str
    diagnostic_event_id: str | None
    diagnostic_summary: str
    diagnostic_category: str
    diagnostic_confidence: float
    original_content: str
    source_language: str = "en"
    source_channel: str | None = None
    reply_recipient: str | None = None
    reply_thread_context: str | None = None
    retrieved_citations: Sequence[Mapping[str, Any]] = ()
    conversation_history: Sequence[Mapping[str, Any]] = ()
    extracted_fields: ExtractedOrderFields | None = None


class ResolutionGovernanceEvaluationStage(StrEnum):
    """WHEN a proposal is being evaluated by central governance.

    The decision-id seed (see resolution_governance_gate._decision_seed)
    must vary by stage: a proposal gets exactly one PROPOSAL_BUILD
    evaluation when it's first created, and may later get a SEPARATE
    DELIVERY_REVALIDATION evaluation if a human revises the reply before
    delivery. These are two distinct decisions about the same proposal --
    without a stage component in the seed, both compute the identical
    decision_id and the second one always collides with the write-once
    governance ledger (it doesn't matter what the second verdict is; the
    insert fails before the verdict is ever returned).
    """

    PROPOSAL_BUILD = "proposal_build"
    DELIVERY_REVALIDATION = "delivery_revalidation"


@dataclass(frozen=True, slots=True)
class ResolutionGovernanceGateRequest:
    """Application-layer governance input for a proposed resolution."""

    proposal_id: ResolutionProposalId
    tenant_id: str
    session_id: str
    execution_id: str
    dispatch_id: str
    diagnostic_event_id: str | None
    diagnostic_summary: str
    diagnostic_category: str
    diagnostic_confidence: float
    original_content: str
    proposed_customer_reply: str
    resolution_category: str
    recommended_actions: tuple[Mapping[str, Any], ...]
    evidence: tuple[Mapping[str, Any], ...]
    local_supervisor_verdict: ResolutionSupervisorVerdict
    local_governance_verdict: ResolutionGovernanceVerdict
    local_autonomy_decision: ResolutionAutonomyDecision
    local_status: ResolutionProposalStatus
    local_reasons: tuple[str, ...]
    evaluation_stage: ResolutionGovernanceEvaluationStage
    reply_segments: tuple[Mapping[str, Any], ...] = ()
    source_language: str = "en"
    source_channel: str | None = None
    reply_recipient: str | None = None
    reply_thread_context: str | None = None
    # True for ANY verdict-override reply (see
    # reply_is_verdict_override_template in create_proposal), regardless of
    # outcome (approved / denied / needs_more_info): a tenant-authored,
    # dual-control-approved template that only ever renders because a
    # specialized verdict already resolved the case. Its factual claims
    # are grounded in that verdict, not a KB citation -- "this item falls
    # outside our warranty period" is exactly as pre-approved a statement
    # as "we're processing a replacement". The central grounding gate
    # exempts it from per-claim KB-citation checking instead of grading
    # text it was never meant to carry citations for. Never set for
    # LLM-drafted free text.
    reply_is_preapproved_template: bool = False


@dataclass(frozen=True, slots=True)
class ResolutionGovernanceGateResult:
    """Central governance verdict for a proposed resolution."""

    governance_verdict: ResolutionGovernanceVerdict
    governance_decision_id: uuid.UUID | None = None


class ResolutionGovernanceGateProtocol(Protocol):
    """Application-layer interface for central resolution governance."""

    async def evaluate_resolution_proposal(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> ResolutionGovernanceGateResult: ...


@dataclass(frozen=True, slots=True)
class _GateDecision:
    supervisor_verdict: ResolutionSupervisorVerdict
    governance_verdict: ResolutionGovernanceVerdict
    autonomy_decision: ResolutionAutonomyDecision
    status: ResolutionProposalStatus
    reasons: tuple[str, ...]
    governance_decision_id: uuid.UUID | None = None


class ResolutionRuntime:
    """Create deterministic, customer-safe resolution proposals."""

    def __init__(
        self,
        *,
        persistence: ResolutionProposalPersistenceProtocol,
        governance_gate: ResolutionGovernanceGateProtocol | None = None,
        conversation_generator: ConversationGenerationRuntimeProtocol | None = None,
        tenant_configuration_repository: TenantConfigurationRepository | None = None,
        auto_approve_threshold: float = _DEFAULT_AUTO_APPROVE_THRESHOLD,
        inventory_availability_checker: InventoryAvailabilityChecker | None = None,
    ) -> None:
        if auto_approve_threshold < 0 or auto_approve_threshold > 1:
            raise ValueError("auto_approve_threshold must be between 0 and 1")
        self._persistence = persistence
        self._governance_gate = governance_gate
        self._auto_approve_threshold = auto_approve_threshold
        self._tenant_configuration_repository = tenant_configuration_repository
        self._conversation_generator = (
            conversation_generator or GroundedConversationGenerationRuntime()
        )
        self._inventory_availability_checker = inventory_availability_checker

    async def create_proposal(
        self,
        request: ResolutionProposalRequest,
    ) -> ResolutionProposalRecord:
        """Persist and return the deterministic proposal for a diagnostic."""

        evidence = _normalise_evidence(request.retrieved_citations)
        taxonomy = await resolve_resolution_taxonomy_policy(
            repository=self._tenant_configuration_repository,
            tenant_id=request.tenant_id,
        )
        warranty_refund_policy = await resolve_warranty_refund_policy(
            repository=self._tenant_configuration_repository,
            tenant_id=request.tenant_id,
        )
        category = _resolution_category(
            diagnostic_category=request.diagnostic_category,
            taxonomy=taxonomy,
        )
        reply_draft = await self._generate_reply_draft(
            request=request,
            category=category,
            evidence=evidence,
        )
        reply_segments = tuple(segment.to_dict() for segment in reply_draft.segments)
        reply = render_grounded_reply(reply_draft)
        now = datetime.now(tz=timezone.utc)
        recommended_actions = _recommended_actions(
            category,
            taxonomy,
            request.extracted_fields,
            warranty_refund_policy=warranty_refund_policy,
            now=now,
        )
        recommended_actions = await _apply_availability_gating(
            recommended_actions,
            policy=warranty_refund_policy,
            tenant_id=request.tenant_id,
            extracted_fields=request.extracted_fields,
            availability_checker=self._inventory_availability_checker,
        )
        recommended_actions = _attach_resolution_verdicts(
            recommended_actions,
            extracted_fields=request.extracted_fields,
        )
        verdict_reply = await _apply_resolution_verdict_override(
            recommended_actions=recommended_actions,
            tenant_configuration_repository=self._tenant_configuration_repository,
            tenant_id=request.tenant_id,
            channel=request.source_channel,
        )
        verdict_summary = _first_resolution_verdict(recommended_actions)
        # An APPROVED verdict's whole purpose is to state the exact
        # commitment ("approved for replacement") the baseline
        # unsupported-promise guard exists to catch from an UNAUTHORIZED
        # LLM draft. This reply isn't LLM-drafted and isn't unauthorized:
        # it's a tenant-authored, dual-control-approved template that
        # only ever renders because a specialized verdict already
        # confirmed eligibility. Scoped to APPROVED only — DENIED/
        # NEEDS_MORE_INFO overrides (including the unchanged
        # cannot_determine probe path) keep the guard exactly as before.
        reply_is_approved_verdict_override = (
            verdict_reply is not None
            and verdict_summary is not None
            and verdict_summary.get("outcome")
            == ResolutionVerdictOutcome.APPROVED.value
        )
        # Central grounding exemption keys on the MECHANISM (is this any
        # verdict-override template?), not the outcome. A denied or needs-
        # more-info override is JUST AS tenant-authored and dual-control-
        # approved as an approved one -- "this item falls outside our
        # warranty period" is exactly as pre-approved a commitment as
        # "we're processing a replacement". The grounding gate exists to
        # catch LLM-INVENTED claims; an authored template has none. Wider
        # than reply_is_approved_verdict_override (which stays scoped to
        # APPROVED for the unrelated local promise-pattern guard above).
        reply_is_verdict_override_template = verdict_reply is not None
        if verdict_reply is not None:
            # reply_segments was captured from the ORIGINAL LLM draft above
            # (line ~367), before this override exists. Recompute it from
            # the text that will actually be sent -- every derived artifact
            # of the reply must move in lockstep with the reply itself, or
            # a downstream gate (grounding) grades a draft the customer
            # will never see while the real outbound text goes unchecked.
            reply = verdict_reply
            reply_segments = (
                GroundedReplySegment(
                    kind="claim", text=verdict_reply, citation_ranks=()
                ).to_dict(),
            )
        autonomy_policy = await resolve_resolution_autonomy_policy(
            repository=self._tenant_configuration_repository,
            tenant_id=request.tenant_id,
        )
        gate = _evaluate_gate(
            category=category,
            original_content=request.original_content,
            reply=reply,
            evidence=evidence,
            autonomy_policy=autonomy_policy,
            taxonomy=taxonomy,
            recommended_actions=recommended_actions,
            extracted_fields=request.extracted_fields,
            skip_unsupported_commitment_check=reply_is_approved_verdict_override,
        )
        proposal_id = derive_resolution_proposal_id(
            tenant_id=request.tenant_id,
            session_id=request.session_id,
            execution_id=request.execution_id,
            dispatch_id=request.dispatch_id,
            diagnostic_event_id=request.diagnostic_event_id,
            diagnostic_event_type=_DIAGNOSTIC_EVENT_TYPE,
        )
        existing = await self._persistence.get_resolution_proposal(
            str(proposal_id),
            expected_tenant_id=request.tenant_id,
        )
        if existing is not None:
            return existing

        gate = await self._evaluate_central_governance(
            ResolutionGovernanceGateRequest(
                proposal_id=proposal_id,
                tenant_id=request.tenant_id,
                session_id=request.session_id,
                execution_id=request.execution_id,
                dispatch_id=request.dispatch_id,
                diagnostic_event_id=request.diagnostic_event_id,
                diagnostic_summary=request.diagnostic_summary,
                diagnostic_category=request.diagnostic_category,
                diagnostic_confidence=request.diagnostic_confidence,
                original_content=request.original_content,
                proposed_customer_reply=reply,
                resolution_category=category,
                recommended_actions=recommended_actions,
                evidence=evidence,
                local_supervisor_verdict=gate.supervisor_verdict,
                local_governance_verdict=gate.governance_verdict,
                local_autonomy_decision=gate.autonomy_decision,
                local_status=gate.status,
                local_reasons=gate.reasons,
                evaluation_stage=ResolutionGovernanceEvaluationStage.PROPOSAL_BUILD,
                reply_segments=reply_segments,
                source_language=_normalise_language(request.source_language),
                source_channel=request.source_channel,
                reply_recipient=request.reply_recipient,
                reply_thread_context=request.reply_thread_context,
                reply_is_preapproved_template=reply_is_verdict_override_template,
            )
        )

        record = ResolutionProposalRecord(
            proposal_id=proposal_id,
            tenant_id=request.tenant_id,
            session_id=request.session_id,
            execution_id=request.execution_id,
            dispatch_id=request.dispatch_id,
            diagnostic_event_id=request.diagnostic_event_id,
            proposed_customer_reply=reply,
            source_language=_normalise_language(request.source_language),
            resolution_category=category,
            confidence=_clamp_confidence(request.diagnostic_confidence),
            recommended_actions=recommended_actions,
            evidence=evidence,
            supervisor_verdict=gate.supervisor_verdict,
            governance_verdict=gate.governance_verdict,
            autonomy_decision=gate.autonomy_decision,
            status=gate.status,
            created_at=now,
            updated_at=now,
            governance_decision_id=gate.governance_decision_id,
        )
        return await self._persistence.create_resolution_proposal(
            record,
            expected_tenant_id=request.tenant_id,
        )

    async def _generate_reply_draft(
        self,
        *,
        request: ResolutionProposalRequest,
        category: str,
        evidence: tuple[Mapping[str, Any], ...],
    ) -> GroundedReplyDraft:
        try:
            result = await self._conversation_generator.generate_reply(
                ConversationGenerationRequest(
                    tenant_id=request.tenant_id,
                    session_id=request.session_id,
                    diagnostic_summary=request.diagnostic_summary,
                    diagnostic_category=category,
                    diagnostic_confidence=request.diagnostic_confidence,
                    original_content=request.original_content,
                    source_language=_normalise_language(request.source_language),
                    evidence=evidence,
                    conversation_history=tuple(
                        dict(turn) for turn in request.conversation_history
                    ),
                    target_language=CANONICAL_LANGUAGE,
                )
            )
            return result.draft
        except Exception:  # noqa: BLE001
            return GroundedReplyDraft(
                language=CANONICAL_LANGUAGE,
                segments=(
                    GroundedReplySegment(
                        kind="claim",
                        text=(
                            "A customer-facing reply could not be grounded "
                            "automatically for this issue."
                        ),
                        citation_ranks=(),
                    ),
                ),
            )

    async def _evaluate_central_governance(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> _GateDecision:
        if self._governance_gate is None:
            return _fail_closed_gate_decision(
                governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
                reason="resolution_governance_gate_missing",
            )
        try:
            result = await self._governance_gate.evaluate_resolution_proposal(
                request
            )
        except Exception:  # noqa: BLE001
            return _fail_closed_gate_decision(
                governance_verdict=ResolutionGovernanceVerdict.DENY,
                reason="resolution_governance_gate_failed",
            )
        return _map_central_governance_result(request, result)


class ResolutionOutboundDraftRuntime:
    """Create durable, no-send outbound drafts from resolution proposals."""

    def __init__(
        self,
        *,
        persistence: ResolutionOutboundDraftPersistenceProtocol,
        translation_runtime: TranslationRuntime | None = None,
    ) -> None:
        self._persistence = persistence
        self._translation_runtime = translation_runtime

    async def create_draft_for_proposal(
        self,
        proposal: ResolutionProposalRecord,
    ) -> ResolutionOutboundDraftRecord:
        """Persist and return the deterministic draft for a proposal."""

        draft_id = derive_resolution_outbound_draft_id(
            tenant_id=proposal.tenant_id,
            proposal_id=str(proposal.proposal_id),
        )
        existing = await self._persistence.get_resolution_outbound_draft(
            str(draft_id),
            expected_tenant_id=proposal.tenant_id,
        )
        if existing is not None:
            return existing

        canonical_reply = proposal.proposed_customer_reply
        localized_reply = await self._localized_reply(
            canonical_reply=canonical_reply,
            proposal=proposal,
        )
        now = datetime.now(tz=timezone.utc)
        record = ResolutionOutboundDraftRecord(
            draft_id=draft_id,
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.proposal_id,
            session_id=_required_proposal_lineage(
                proposal.session_id, "session_id"
            ),
            execution_id=_required_proposal_lineage(
                proposal.execution_id, "execution_id"
            ),
            dispatch_id=proposal.dispatch_id,
            diagnostic_event_id=proposal.diagnostic_event_id,
            governance_decision_id=proposal.governance_decision_id,
            status=resolution_outbound_draft_status_for_proposal(proposal),
            draft_body=localized_reply,
            draft_body_sha256=_sha256_hex(localized_reply),
            resolution_category=proposal.resolution_category,
            confidence=proposal.confidence,
            created_at=now,
            updated_at=now,
            metadata={
                "canonical_reply": canonical_reply,
                "localized_reply": localized_reply,
                "source_language": proposal.source_language,
            },
        )
        return await self._persistence.create_resolution_outbound_draft(
            record,
            expected_tenant_id=proposal.tenant_id,
        )

    async def _localized_reply(
        self,
        *,
        canonical_reply: str,
        proposal: ResolutionProposalRecord,
    ) -> str:
        source_language = _normalise_language(proposal.source_language)
        if source_language == CANONICAL_LANGUAGE:
            return canonical_reply
        if self._translation_runtime is None:
            return canonical_reply
        try:
            envelope = await self._translation_runtime.egress.localize(
                EgressLocalizeRequest(
                    canonical=TranslationPayload(
                        text=canonical_reply,
                        language=CANONICAL_LANGUAGE,
                    ),
                    context=LocalizationContext(
                        target_language=source_language,
                        formality=derive_formality(
                            base_language=source_language
                        ),
                    ),
                    seed=(
                        "resolution-draft|"
                        f"{proposal.tenant_id}|{proposal.proposal_id}|"
                        f"{source_language}"
                    ),
                    correlation_id=proposal.dispatch_id,
                    request_id=str(proposal.proposal_id),
                    tenant_id=proposal.tenant_id,
                    authority=AuthorityContext(
                        tenant_id=TenantId(proposal.tenant_id),
                        capabilities=frozenset(
                            {
                                OperationalAct.BOUNDARY_TRANSLATION_EGRESS.value
                            }
                        ),
                    ),
                    attributes={"source_language": source_language},
                )
            )
        except Exception:  # noqa: BLE001
            return canonical_reply
        result = envelope.result
        localization = getattr(result, "localization", None)
        localized_payload = getattr(localization, "localized_payload", None)
        localized_text = getattr(localized_payload, "text", None)
        if envelope.is_fully_clean and isinstance(localized_text, str):
            return localized_text
        return canonical_reply


def _required_proposal_lineage(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(
            f"resolution proposal {field_name} is required for draft creation"
        )
    return value


def resolution_proposal_timeline_payload(
    record: ResolutionProposalRecord,
) -> dict[str, Any]:
    """Build the append-only timeline payload for a resolution proposal."""

    payload = record.to_dict()
    payload["send_eligible"] = resolution_proposal_is_send_eligible(record)
    payload["requires_human_approval"] = (
        record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    )
    return payload


def resolution_outbound_draft_status_for_proposal(
    record: ResolutionProposalRecord,
) -> ResolutionOutboundDraftStatus:
    """Map proposal state to a no-send draft state."""

    if resolution_proposal_is_send_eligible(record):
        return ResolutionOutboundDraftStatus.READY
    if record.status is ResolutionProposalStatus.DENIED:
        return ResolutionOutboundDraftStatus.DENIED
    if record.status is ResolutionProposalStatus.FAILED:
        return ResolutionOutboundDraftStatus.FAILED
    return ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL


def resolution_outbound_draft_timeline_payload(
    *,
    draft: ResolutionOutboundDraftRecord,
    proposal: ResolutionProposalRecord,
) -> dict[str, Any]:
    """Build the append-only timeline payload for an outbound draft."""

    payload = draft.to_dict()
    payload["send_eligible"] = resolution_proposal_is_send_eligible(proposal)
    return payload


def resolution_proposal_is_send_eligible(
    record: ResolutionProposalRecord,
) -> bool:
    """Return true only when central governance lineage is persisted."""

    return (
        record.status is ResolutionProposalStatus.SEND_ELIGIBLE
        and record.governance_decision_id is not None
    )


def _map_central_governance_result(
    request: ResolutionGovernanceGateRequest,
    result: ResolutionGovernanceGateResult,
) -> _GateDecision:
    decision_id = result.governance_decision_id
    if decision_id is None:
        return _fail_closed_gate_decision(
            governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
            reason="resolution_governance_decision_id_missing",
        )
    if result.governance_verdict is ResolutionGovernanceVerdict.DENY:
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.FAIL,
            governance_verdict=ResolutionGovernanceVerdict.DENY,
            autonomy_decision=ResolutionAutonomyDecision.DENIED,
            status=ResolutionProposalStatus.DENIED,
            reasons=("central_governance_denied",),
            governance_decision_id=decision_id,
        )
    if _local_gate_denied(request):
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.FAIL,
            governance_verdict=request.local_governance_verdict,
            autonomy_decision=ResolutionAutonomyDecision.DENIED,
            status=ResolutionProposalStatus.DENIED,
            reasons=tuple(request.local_reasons or ("local_governance_denied",)),
            governance_decision_id=decision_id,
        )
    if result.governance_verdict is not ResolutionGovernanceVerdict.ALLOW:
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
            governance_verdict=result.governance_verdict,
            autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
            status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
            reasons=(f"central_governance_{result.governance_verdict.value}",),
            governance_decision_id=decision_id,
        )
    if _local_gate_passed(request):
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.PASS,
            governance_verdict=ResolutionGovernanceVerdict.ALLOW,
            autonomy_decision=ResolutionAutonomyDecision.AUTO_APPROVED,
            status=ResolutionProposalStatus.SEND_ELIGIBLE,
            reasons=("local_and_central_governance_allowed",),
            governance_decision_id=decision_id,
        )
    return _GateDecision(
        supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
        governance_verdict=request.local_governance_verdict,
        autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
        status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
        reasons=tuple(request.local_reasons or ("local_governance_not_auto_approved",)),
        governance_decision_id=decision_id,
    )


def _local_gate_passed(request: ResolutionGovernanceGateRequest) -> bool:
    return (
        request.local_status is ResolutionProposalStatus.AUTO_APPROVED
        and request.local_supervisor_verdict is ResolutionSupervisorVerdict.PASS
        and request.local_governance_verdict is ResolutionGovernanceVerdict.ALLOW
        and request.local_autonomy_decision
        is ResolutionAutonomyDecision.AUTO_APPROVED
    )


def _local_gate_denied(request: ResolutionGovernanceGateRequest) -> bool:
    return (
        request.local_status is ResolutionProposalStatus.DENIED
        or request.local_supervisor_verdict is ResolutionSupervisorVerdict.FAIL
        or request.local_governance_verdict is ResolutionGovernanceVerdict.DENY
        or request.local_autonomy_decision is ResolutionAutonomyDecision.DENIED
    )


def _fail_closed_gate_decision(
    *,
    governance_verdict: ResolutionGovernanceVerdict,
    reason: str,
) -> _GateDecision:
    if governance_verdict is ResolutionGovernanceVerdict.DENY:
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.FAIL,
            governance_verdict=ResolutionGovernanceVerdict.DENY,
            autonomy_decision=ResolutionAutonomyDecision.DENIED,
            status=ResolutionProposalStatus.DENIED,
            reasons=(reason,),
        )
    return _GateDecision(
        supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
        governance_verdict=governance_verdict,
        autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
        status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
        reasons=(reason,),
    )


def _resolution_category(
    *,
    diagnostic_category: str,
    taxonomy: ResolutionTaxonomyPolicy,
) -> str:
    if diagnostic_category == UNCLASSIFIED_CATEGORY_ID:
        return UNCLASSIFIED_CATEGORY_ID
    if diagnostic_category in taxonomy.category_ids():
        return diagnostic_category
    # Defense-in-depth: the diagnostic stage already clamps unrecognized
    # categories to "unclassified", but a future caller that skips that step
    # must not silently adopt an unvalidated category string.
    return UNCLASSIFIED_CATEGORY_ID


class ResolutionVerdictOutcome(StrEnum):
    """Domain-agnostic outcome a specialized resolution path can report.

    This is the generic extension contract _apply_resolution_verdict_
    override consumes. Warranty/refund eligibility (W1) is the first
    producer; any other tenant-specific determination (a bank's KYC
    check, a telecom's SIM-swap eligibility) populates the same three
    values without the dispatcher or the LLM drafter knowing anything
    domain-specific changed.
    """

    APPROVED = "approved"
    DENIED = "denied"
    NEEDS_MORE_INFO = "needs_more_info"


@dataclass(frozen=True, slots=True)
class ResolutionVerdictSummary:
    """Domain-agnostic verdict summary attached to a recommended action.

    ``outcome_purpose_key`` is opaque to the dispatcher — it is whatever
    vocabulary the producing domain uses (a remedy name, a failed-rule
    name, a missing-field name) — and combines with ``outcome`` to form
    the template lookup key ``resolution.{outcome}.{outcome_purpose_key}``
    against the tenant's own approved Templates KB. ``substitution_values``
    are placeholder values for that template's content, also opaque to
    the dispatcher.
    """

    outcome: ResolutionVerdictOutcome
    outcome_purpose_key: str
    missing_fields: tuple[str, ...] = ()
    substitution_values: Mapping[str, str | None] = dataclass_field(
        default_factory=dict[str, str | None]
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "outcome_purpose_key": self.outcome_purpose_key,
            "missing_fields": list(self.missing_fields),
            "substitution_values": dict(self.substitution_values),
        }


def _recommended_actions(
    category: str,
    taxonomy: ResolutionTaxonomyPolicy,
    extracted_fields: ExtractedOrderFields | None = None,
    *,
    warranty_refund_policy: WarrantyRefundPolicy | None = None,
    now: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    actions = taxonomy.actions_for(category)
    if extracted_fields is None and warranty_refund_policy is None:
        return actions
    resolved_fields = (
        extracted_fields if extracted_fields is not None else ExtractedOrderFields()
    )
    resolved_now = now if now is not None else datetime.now(timezone.utc)
    result: list[Mapping[str, Any]] = []
    for action in actions:
        merged = (
            _merge_extracted_fields(action, resolved_fields)
            if extracted_fields is not None
            else dict(action)
        )
        result.append(
            _attach_warranty_refund_eligibility(
                merged,
                extracted_fields=resolved_fields,
                policy=warranty_refund_policy,
                now=resolved_now,
            )
        )
    return tuple(result)


def _attach_warranty_refund_eligibility(
    action: Mapping[str, Any],
    *,
    extracted_fields: ExtractedOrderFields,
    policy: WarrantyRefundPolicy | None,
    now: datetime,
) -> Mapping[str, Any]:
    """Embed a W1 eligibility determination into a recommended action's dict
    when the action's taxonomy "type" is a configured warranty/refund claim
    type. Rides along through the existing recommended_actions JSON field —
    no schema change. An action whose type the tenant hasn't configured
    warranty_refund_rules for is returned unchanged: W1 has nothing to say
    about it, and no eligibility key is added (distinct from a
    cannot_determine verdict, which means the determination ran and could
    not conclude).

    Stays synchronous and pure, exactly like W1/W2 — the availability-
    gated remedy refinement (W3) is a separate async post-processing pass
    (_apply_availability_gating, called from create_proposal) so this
    function's existing callers/tests are unaffected by W3's addition.
    """
    if policy is None:
        return action
    action_type = action.get("type")
    if not isinstance(action_type, str) or not action_type.strip():
        return action
    claim_type = action_type.strip()
    if policy.required_evidence_for(claim_type) is None:
        return action
    determination = determine_eligibility(
        claim_type=claim_type,
        extracted_fields=extracted_fields,
        policy=policy,
        now=now,
    )
    merged = dict(action)
    merged["warranty_refund_eligibility"] = _eligibility_determination_to_dict(
        determination
    )
    return merged


async def _apply_availability_gating(
    actions: tuple[Mapping[str, Any], ...],
    *,
    policy: WarrantyRefundPolicy | None,
    tenant_id: str,
    extracted_fields: ExtractedOrderFields | None,
    availability_checker: InventoryAvailabilityChecker | None,
) -> tuple[Mapping[str, Any], ...]:
    """W3: refine W1's naive "first ladder step" remedy into the first
    AVAILABLE one, for every eligible action embedded by
    _attach_warranty_refund_eligibility. The only I/O in the whole
    recommended_actions pipeline lives here, isolated from the pure
    embedding step above.
    """
    if policy is None:
        return actions
    resolved_fields = (
        extracted_fields if extracted_fields is not None else ExtractedOrderFields()
    )
    result: list[Mapping[str, Any]] = []
    for action in actions:
        raw_eligibility = action.get("warranty_refund_eligibility")
        if not isinstance(raw_eligibility, Mapping):
            result.append(action)
            continue
        eligibility = cast(Mapping[str, Any], raw_eligibility)
        if eligibility.get("verdict") != EligibilityVerdict.ELIGIBLE.value:
            result.append(action)
            continue
        claim_type = eligibility.get("claim_type")
        if not isinstance(claim_type, str):
            result.append(action)
            continue
        selection = await select_available_remedy(
            claim_type=claim_type,
            policy=policy,
            tenant_id=tenant_id,
            extracted_fields=resolved_fields,
            availability_checker=availability_checker,
        )
        merged_eligibility = dict(eligibility)
        merged_eligibility["recommended_remedy"] = selection.remedy
        merged_eligibility["recommended_remedy_availability"] = (
            selection.availability.value if selection.availability else None
        )
        merged_action = dict(action)
        merged_action["warranty_refund_eligibility"] = merged_eligibility
        result.append(merged_action)
    return tuple(result)


def _attach_resolution_verdicts(
    actions: tuple[Mapping[str, Any], ...],
    *,
    extracted_fields: ExtractedOrderFields | None,
) -> tuple[Mapping[str, Any], ...]:
    """Map each action's warranty/refund eligibility verdict (if any) onto
    the generic ResolutionVerdictSummary contract
    _apply_resolution_verdict_override consumes, embedding it under the
    domain-agnostic "resolution_verdict" key alongside the existing
    "warranty_refund_eligibility" key — which is left untouched, since
    W2's approval-queue wiring (agent_tasks._first_warranty_refund_
    eligible_action) still reads it directly.

    This is the ONLY place warranty-specific verdict shape knowledge
    exists outside warranty_refund_eligibility.py itself. Any other
    specialized resolution path would add its own analogous attach step
    here (or attach "resolution_verdict" directly at its own embedding
    site) — never inside the dispatcher, never inside the drafter. Runs
    after _apply_availability_gating so an ELIGIBLE outcome's
    outcome_purpose_key reflects the availability-checked final remedy,
    not W1's naive first-ladder-step guess.
    """
    result: list[Mapping[str, Any]] = []
    for action in actions:
        eligibility = action.get("warranty_refund_eligibility")
        if not isinstance(eligibility, Mapping):
            result.append(action)
            continue
        summary = _warranty_refund_eligibility_to_resolution_verdict(
            cast(Mapping[str, Any], eligibility),
            extracted_fields=extracted_fields,
        )
        if summary is None:
            result.append(action)
            continue
        merged = dict(action)
        merged["resolution_verdict"] = summary.to_dict()
        result.append(merged)
    return tuple(result)


def _warranty_refund_eligibility_to_resolution_verdict(
    eligibility: Mapping[str, Any],
    *,
    extracted_fields: ExtractedOrderFields | None,
) -> ResolutionVerdictSummary | None:
    """The warranty-specific mapping: EligibilityDetermination (as the
    dict _eligibility_determination_to_dict produces, post-W3 remedy
    gating) -> the generic ResolutionVerdictSummary. Returns None when
    there's genuinely nothing actionable to report (e.g. cannot_determine
    with no specific missing field, or eligible with no remedy
    configured) — mirroring the old probe's fail-closed "nothing to
    probe for" path exactly.
    """
    verdict = eligibility.get("verdict")
    raw_claim_type = eligibility.get("claim_type")
    claim_type = raw_claim_type if isinstance(raw_claim_type, str) else None

    if verdict == EligibilityVerdict.ELIGIBLE.value:
        remedy = eligibility.get("recommended_remedy")
        if not isinstance(remedy, str) or not remedy:
            return None
        return ResolutionVerdictSummary(
            outcome=ResolutionVerdictOutcome.APPROVED,
            outcome_purpose_key=remedy,
            substitution_values=_probe_substitution_values(
                claim_type=claim_type,
                missing_fields=[],
                extracted_fields=extracted_fields,
            ),
        )

    if verdict == EligibilityVerdict.INELIGIBLE.value:
        failed_rule = _first_failed_grounding_check(eligibility.get("grounding"))
        if failed_rule is None:
            return None
        return ResolutionVerdictSummary(
            outcome=ResolutionVerdictOutcome.DENIED,
            outcome_purpose_key=failed_rule,
            substitution_values=_probe_substitution_values(
                claim_type=claim_type,
                missing_fields=[],
                extracted_fields=extracted_fields,
            ),
        )

    if verdict == EligibilityVerdict.CANNOT_DETERMINE.value:
        missing_evidence = eligibility.get("missing_evidence")
        missing_fields = (
            [
                field
                for field in cast(list[object], missing_evidence)
                if isinstance(field, str)
            ]
            if isinstance(missing_evidence, list)
            else []
        )
        if not missing_fields:
            return None
        return ResolutionVerdictSummary(
            outcome=ResolutionVerdictOutcome.NEEDS_MORE_INFO,
            outcome_purpose_key=f"missing_{missing_fields[0]}",
            missing_fields=tuple(missing_fields),
            substitution_values=_probe_substitution_values(
                claim_type=claim_type,
                missing_fields=missing_fields,
                extracted_fields=extracted_fields,
            ),
        )

    return None


def _first_failed_grounding_check(grounding: object) -> str | None:
    if not isinstance(grounding, list):
        return None
    for check in cast(list[object], grounding):
        if not isinstance(check, Mapping):
            continue
        check_mapping = cast(Mapping[str, Any], check)
        if check_mapping.get("passed") is False:
            name = check_mapping.get("name")
            if isinstance(name, str) and name:
                return name
    return None


async def _apply_resolution_verdict_override(
    *,
    recommended_actions: tuple[Mapping[str, Any], ...],
    tenant_configuration_repository: TenantConfigurationRepository | None,
    tenant_id: str,
    channel: str | None,
) -> str | None:
    """Generic, domain-agnostic reply-override dispatch.

    Generalizes the old single-purpose cannot_determine probe (W4) to
    all three ResolutionVerdictSummary outcomes. Any specialized
    resolution path — W1 warranty/refund eligibility today, any other
    tenant-specific determination tomorrow — can attach a
    ResolutionVerdictSummary to a recommended action (under the
    "resolution_verdict" key) to have this function render a
    tenant-authored, byte-exact customer message in place of the
    LLM-drafted reply. This function knows nothing about what an
    "outcome" or "outcome_purpose_key" MEANS — it only resolves
    (tenant_id, "resolution.{outcome}.{outcome_purpose_key}", channel)
    against the tenant's own approved Templates KB and substitutes the
    values the verdict producer supplied. Fail-closed exactly like the
    W4 probe this generalizes: no approved template -> None, the
    caller's existing reply stands unchanged — never fabricated. This
    only ever returns DATA: the unchanged governance gate and explicit
    human-approval chain are the only path that can ever transmit it —
    this function cannot cause a send.
    """
    if tenant_configuration_repository is None or channel is None:
        return None
    summary = _first_resolution_verdict(recommended_actions)
    if summary is None:
        return None
    outcome = summary.get("outcome")
    purpose_key = summary.get("outcome_purpose_key")
    if not isinstance(outcome, str) or not isinstance(purpose_key, str) or not purpose_key:
        return None
    purpose = f"resolution.{outcome}.{purpose_key}"
    runtime = TenantConfigurationRuntime(repository=tenant_configuration_repository)
    template = await runtime.get_approved_template(
        tenant_id=tenant_id,
        purpose=purpose,
        channel=channel,
    )
    if template is None:
        return None
    raw_values = summary.get("substitution_values")
    values = (
        dict(cast(Mapping[str, Any], raw_values))
        if isinstance(raw_values, Mapping)
        else {}
    )
    return substitute_placeholders(template.content, values)


def _first_resolution_verdict(
    recommended_actions: tuple[Mapping[str, Any], ...],
) -> Mapping[str, Any] | None:
    for action in recommended_actions:
        raw_verdict = action.get("resolution_verdict")
        if isinstance(raw_verdict, Mapping):
            return cast(Mapping[str, Any], raw_verdict)
    return None


def _probe_substitution_values(
    *,
    claim_type: str | None,
    missing_fields: list[str],
    extracted_fields: ExtractedOrderFields | None,
) -> dict[str, str | None]:
    values: dict[str, str | None] = {
        "missing_fields": ", ".join(_humanize_field(field) for field in missing_fields),
    }
    if claim_type is not None:
        values["claim_type"] = _humanize_field(claim_type)
    if extracted_fields is not None:
        for name in EXTRACTED_ORDER_FIELD_NAMES:
            field: ExtractedField = getattr(extracted_fields, name)
            values[name] = field.value
    return values


def _humanize_field(name: str) -> str:
    # Lowercase, space-joined — meant to read inline in mid-sentence
    # template prose (e.g. "we still need: purchase date, seller"), not
    # as a standalone capitalized label.
    return name.replace("_", " ")


def _eligibility_determination_to_dict(
    determination: EligibilityDetermination,
) -> dict[str, Any]:
    return {
        "claim_type": determination.claim_type,
        "verdict": determination.verdict.value,
        "recommended_remedy": determination.recommended_remedy,
        "recommended_remedy_availability": None,
        "missing_evidence": list(determination.missing_evidence),
        "grounding": [
            {
                "name": check.name,
                "passed": check.passed,
                "rule": check.rule,
                "evidence_field": check.evidence_field,
                "evidence_value": check.evidence_value,
                "evidence_confidence": check.evidence_confidence,
                "evidence_source": check.evidence_source,
            }
            for check in determination.grounding
        ],
    }


def _merge_extracted_fields(
    action: Mapping[str, Any],
    extracted_fields: ExtractedOrderFields,
) -> Mapping[str, Any]:
    """Merge real extracted values into the action's template dict — this
    is the precise fix for the unknown_order/unknown_sku bug: actions built
    from category+taxonomy alone never carried real ticket data, so
    downstream fallback chains (orchestration.py) always hit their
    fabricated-placeholder branch. An explicit tenant-configured value on
    the template (rare; templates are empty by default) still wins over
    extraction. A None extracted value never overwrites anything — it
    simply leaves the key unset, which downstream code reads as "missing"
    honestly rather than as a string that looks like data.
    """
    merged = dict(action)
    for name in EXTRACTED_ORDER_FIELD_NAMES:
        field: ExtractedField = getattr(extracted_fields, name)
        if field.value is not None and merged.get(name) is None:
            merged[name] = field.value
    return merged


# Required for THIS action type to be eligible for auto-approval. Keyed by
# the taxonomy action "type" (matches app.agents.tools.orchestration's
# _ACTION_TOOL_BY_TYPE keys) rather than tool_name, since tool_name can be
# tenant-customized while "type" is the stable taxonomy identifier.
_REQUIRED_EXTRACTION_FIELDS_BY_ACTION_TYPE: Mapping[str, tuple[str, ...]] = {
    "refund_request": ("order_id", "amount"),
    "warranty_claim": ("purchase_date",),
    "replacement_order": ("order_id",),
    "warehouse_repair": (),
}

# confidence levels that are NOT good enough to act on, even though a
# value is present — "low" means the model itself flagged uncertainty
# (e.g. conflicting values in the ticket); "missing" (value is None) is
# handled separately below. Both fail closed identically.
_INSUFFICIENT_CONFIDENCE = frozenset({"low"})


def _extraction_completeness_reasons(
    *,
    recommended_actions: tuple[Mapping[str, Any], ...],
    extracted_fields: ExtractedOrderFields | None,
) -> tuple[str, ...]:
    """Fail-closed extraction gating: an action whose required field is
    missing or low-confidence must route to human approval through the
    SAME reasons-list mechanism a monetary-threshold breach or fraud
    keyword already uses — not a parallel check. A wrong order_id or
    purchase_date feeds a wrong eligibility decision, so "extraction
    didn't find it" is never silently treated as "proceed anyway".
    """
    reasons: list[str] = []
    for action in recommended_actions:
        action_type = action.get("type")
        if not isinstance(action_type, str) or not action_type.strip():
            continue
        required = _REQUIRED_EXTRACTION_FIELDS_BY_ACTION_TYPE.get(
            action_type.strip(), ()
        )
        for field_name in required:
            field = _extracted_field_or_none(extracted_fields, field_name)
            is_insufficient = (
                field is None
                or field.value is None
                or field.confidence in _INSUFFICIENT_CONFIDENCE
            )
            if is_insufficient:
                reasons.append(
                    f"missing_required_extraction_field:{action_type}:{field_name}"
                )
    return tuple(reasons)


def _warranty_refund_cannot_determine_reasons(
    recommended_actions: tuple[Mapping[str, Any], ...],
) -> tuple[str, ...]:
    """A cannot_determine eligibility verdict must reach human review through
    the same reasons-list mechanism every other gate condition uses — never
    silently dropped. Distinct from _extraction_completeness_reasons' fixed
    per-type field list: this is driven by the tenant's own configured
    warranty_refund_rules evidence requirements, which can require fields
    (e.g. seller) that the fixed list does not check at all.
    """
    reasons: list[str] = []
    for action in recommended_actions:
        raw_eligibility = action.get("warranty_refund_eligibility")
        if not isinstance(raw_eligibility, Mapping):
            continue
        eligibility = cast(Mapping[str, Any], raw_eligibility)
        if eligibility.get("verdict") == "cannot_determine":
            claim_type = eligibility.get("claim_type") or action.get("type")
            reasons.append(
                f"warranty_refund_eligibility_cannot_determine:{claim_type}"
            )
    return tuple(reasons)


def _extracted_field_or_none(
    extracted_fields: ExtractedOrderFields | None,
    field_name: str,
) -> ExtractedField | None:
    if extracted_fields is None:
        return None
    value = getattr(extracted_fields, field_name, None)
    return value if isinstance(value, ExtractedField) else None


def _evaluate_gate(
    *,
    category: str,
    original_content: str,
    reply: str,
    evidence: tuple[Mapping[str, Any], ...],
    autonomy_policy: ResolutionAutonomyPolicy,
    taxonomy: ResolutionTaxonomyPolicy,
    recommended_actions: tuple[Mapping[str, Any], ...] = (),
    extracted_fields: ExtractedOrderFields | None = None,
    skip_unsupported_commitment_check: bool = False,
) -> _GateDecision:
    reasons: list[str] = []
    text = f"{original_content} {reply}".lower()
    commitment_kinds = money_or_goods_commitment_kinds(
        recommended_actions=recommended_actions,
        reply=reply,
    )
    evidence_empty = len(evidence) == 0
    if category == UNCLASSIFIED_CATEGORY_ID:
        # Defense-in-depth: even if a future misconfiguration ever placed
        # "unclassified" into autonomy_policy.reply_auto_send_categories,
        # an unclassified ticket must never auto-send.
        reasons.append("unclassified_category_requires_human_approval")
    if evidence_empty:
        reasons.append("missing_citations")
    if _contains_any(text, _SAFETY_KEYWORDS):
        reasons.append("safety_risk")
    if _contains_any(text, _LEGAL_KEYWORDS):
        reasons.append("legal_or_chargeback_risk")
    if _contains_any(text, _FRAUD_KEYWORDS):
        reasons.append("fraud_risk")
    if _contains_any(text, _POLICY_EXCEPTION_KEYWORDS):
        reasons.append("policy_exception")
    if commitment_kinds:
        reasons.append("money_or_goods_commitment_requires_human_approval")
    if _has_conflicting_evidence(evidence):
        reasons.append("conflicting_evidence")
    reasons.extend(
        _extraction_completeness_reasons(
            recommended_actions=recommended_actions,
            extracted_fields=extracted_fields,
        )
    )
    reasons.extend(
        _warranty_refund_cannot_determine_reasons(recommended_actions)
    )
    if not skip_unsupported_commitment_check and (
        _contains_any(reply.lower(), _unsupported_commitment_patterns(taxonomy))
        or _PERSONAL_WARRANTY_COVERAGE_PATTERN.search(reply.lower())
    ):
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.FAIL,
            governance_verdict=ResolutionGovernanceVerdict.DENY,
            autonomy_decision=ResolutionAutonomyDecision.DENIED,
            status=ResolutionProposalStatus.DENIED,
            reasons=("unsupported_refund_replacement_or_warranty_promise",),
        )
    if any(
        reason in reasons
        for reason in ("safety_risk", "legal_or_chargeback_risk", "fraud_risk")
    ):
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
            governance_verdict=ResolutionGovernanceVerdict.ESCALATE,
            autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
            status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
            reasons=tuple(reasons),
        )
    if reasons or category not in autonomy_policy.reply_auto_send_categories:
        return _GateDecision(
            supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
            governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
            autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
            status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
            reasons=tuple(reasons or ("unsupported_auto_category",)),
        )
    return _GateDecision(
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=ResolutionGovernanceVerdict.ALLOW,
        autonomy_decision=ResolutionAutonomyDecision.AUTO_APPROVED,
        status=ResolutionProposalStatus.AUTO_APPROVED,
        reasons=("auto_approval_criteria_met",),
    )


def _normalise_evidence(
    citations: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    evidence: list[dict[str, Any]] = []
    for index, citation in enumerate(citations):
        item: dict[str, Any] = {
            "rank": _int_value(citation.get("rank"), default=index + 1),
            "document_id": _text_value(citation.get("document_id")),
            "title": _text_value(citation.get("title"))
            or "Cited knowledge document",
            "document_type": _text_value(citation.get("document_type")),
            "document_status": _text_value(citation.get("document_status")),
            "score": _float_value(citation.get("score")),
            "chunk_ordinal": _int_value(
                citation.get("chunk_ordinal"),
                default=0,
            ),
            "token_count": _int_value(citation.get("token_count"), default=0),
        }
        for field in _OPTIONAL_EVIDENCE_TEXT_FIELDS:
            value = citation.get(field)
            if isinstance(value, str):
                item[field] = value.strip()
        for field in _OPTIONAL_EVIDENCE_INT_FIELDS:
            value = citation.get(field)
            if isinstance(value, (int, float)):
                item[field] = int(value)
        evidence.append(item)
    return tuple(evidence)


def _has_conflicting_evidence(
    evidence: tuple[Mapping[str, Any], ...]
) -> bool:
    if any(bool(item.get("conflict")) for item in evidence):
        return True
    statuses = {
        str(item.get("document_status")).lower()
        for item in evidence
        if item.get("document_status") is not None
    }
    if not statuses:
        return False
    return any(status not in {"", "active"} for status in statuses)


def _monetary_commitment_exceeds_threshold(
    text: str,
    threshold_cents: int,
    taxonomy: ResolutionTaxonomyPolicy,
) -> bool:
    money_pattern = _money_pattern_for(taxonomy)
    for match in money_pattern.finditer(text):
        amount_text = match.group("prefix") or match.group("suffix")
        if amount_text is None:
            continue
        amount_cents = round(float(amount_text.replace(",", "")) * 100)
        if amount_cents >= threshold_cents:
            return True
    return False


def _money_pattern_for(taxonomy: ResolutionTaxonomyPolicy) -> re.Pattern[str]:
    symbols = sorted(
        taxonomy.monetary_currency_symbols | {"$"}, key=len, reverse=True
    )
    codes = sorted(
        taxonomy.monetary_currency_codes | {"usd", "dollars"}, key=len, reverse=True
    )
    symbol_pattern = "|".join(re.escape(symbol) for symbol in symbols)
    code_pattern = "|".join(re.escape(code) for code in codes)
    return re.compile(
        rf"(?:(?:{symbol_pattern})\s*(?P<prefix>\d+(?:,\d{{3}})*(?:\.\d{{1,2}})?)|"
        rf"(?P<suffix>\d+(?:,\d{{3}})*(?:\.\d{{1,2}})?)\s*(?:{code_pattern}))",
        flags=re.IGNORECASE,
    )


def _unsupported_commitment_patterns(
    taxonomy: ResolutionTaxonomyPolicy,
) -> frozenset[str]:
    return _BASELINE_UNSUPPORTED_PROMISE_PATTERNS | taxonomy.unsupported_commitment_patterns


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _clamp_confidence(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def _normalise_language(language: str) -> str:
    cleaned = language.strip().lower()
    return cleaned or CANONICAL_LANGUAGE


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int_value(value: Any, *, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _float_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


__all__ = [
    "ResolutionGovernanceGateProtocol",
    "ResolutionGovernanceGateRequest",
    "ResolutionGovernanceGateResult",
    "ResolutionOutboundDraftRuntime",
    "ResolutionProposalRequest",
    "ResolutionRuntime",
    "resolution_outbound_draft_status_for_proposal",
    "resolution_outbound_draft_timeline_payload",
    "resolution_proposal_is_send_eligible",
    "resolution_proposal_timeline_payload",
]
