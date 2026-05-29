"""Application-layer runtime for autonomous resolution proposals."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol, Sequence

from app.boundary.translation import (
    CANONICAL_LANGUAGE,
    EgressLocalizeRequest,
    LocalizationContext,
    TranslationPayload,
    TranslationRuntime,
    derive_formality,
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

_DEFAULT_AUTO_APPROVE_THRESHOLD = 0.80
_DIAGNOSTIC_EVENT_TYPE = "diagnostic_analysis_completed"

_SAFE_AUTO_CATEGORIES = frozenset(
    {
        "charging_issue",
        "generic_troubleshooting",
        "connectivity_issue",
        "power_issue",
    }
)

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
        "swollen battery",
        "chemical",
        "fumes",
    }
)
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
_UNSUPPORTED_PROMISE_PATTERNS = frozenset(
    {
        "we will refund",
        "we'll refund",
        "you are eligible for a refund",
        "approved for refund",
        "we will replace",
        "we'll replace",
        "approved for replacement",
        "covered under warranty",
        "warranty covers",
        "guaranteed replacement",
    }
)
_OPTIONAL_EVIDENCE_TEXT_FIELDS = (
    "chunk_id",
    "vector_id",
    "vector_index_name",
    "safe_excerpt",
    "safe_excerpt_sha256",
    "chunk_content_hash",
)
_OPTIONAL_EVIDENCE_INT_FIELDS = (
    "citation_schema_version",
    "document_version",
)
_MONEY_PATTERN = re.compile(
    r"(?:[$]\s*(?P<prefix>\d+(?:,\d{3})*(?:\.\d{1,2})?)|"
    r"(?P<suffix>\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:usd|dollars))",
    flags=re.IGNORECASE,
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
    retrieved_citations: Sequence[Mapping[str, Any]] = ()


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
        auto_approve_threshold: float = _DEFAULT_AUTO_APPROVE_THRESHOLD,
    ) -> None:
        if auto_approve_threshold < 0 or auto_approve_threshold > 1:
            raise ValueError("auto_approve_threshold must be between 0 and 1")
        self._persistence = persistence
        self._governance_gate = governance_gate
        self._auto_approve_threshold = auto_approve_threshold

    async def create_proposal(
        self,
        request: ResolutionProposalRequest,
    ) -> ResolutionProposalRecord:
        """Persist and return the deterministic proposal for a diagnostic."""

        evidence = _normalise_evidence(request.retrieved_citations)
        category = _resolution_category(
            diagnostic_category=request.diagnostic_category,
            original_content=request.original_content,
        )
        reply = _customer_reply(
            category=category,
            evidence=evidence,
            original_content=request.original_content,
        )
        recommended_actions = _recommended_actions(category)
        gate = _evaluate_gate(
            category=category,
            confidence=request.diagnostic_confidence,
            original_content=request.original_content,
            reply=reply,
            evidence=evidence,
            auto_approve_threshold=self._auto_approve_threshold,
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
            )
        )

        now = datetime.now(tz=timezone.utc)
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
    original_content: str,
) -> str:
    category = _slug(diagnostic_category)
    content = original_content.lower()
    if _contains_any(content, ("warranty", "replacement", "replace")):
        return "warranty_replacement_inquiry"
    if _contains_any(content, ("refund", "return", "chargeback")):
        return "returns_refunds_inquiry"
    if _contains_any(content, ("charge", "charging", "charger", "battery", "power")):
        return "charging_issue"
    if category in {"", "unknown", "unclear", "low_confidence"}:
        return "unknown_low_confidence"
    if _contains_any(content, ("troubleshoot", "error", "not working", "broken")):
        return "generic_troubleshooting"
    return category


def _customer_reply(
    *,
    category: str,
    evidence: tuple[Mapping[str, Any], ...],
    original_content: str,
) -> str:
    del original_content
    if not evidence:
        return (
            "Thanks for reaching out. I could not find cited support evidence "
            "for a safe automatic response, so a human reviewer should check "
            "this before we provide next steps. Please share any order details, "
            "product model, screenshots, and the exact issue you are seeing."
        )

    source = _source_reference(evidence)
    if category == "charging_issue":
        return (
            "Thanks for reaching out. Based on the cited support guidance I "
            f"found ({source}), please try these charging checks: confirm the "
            "cable and adapter are firmly connected, test a known-good outlet, "
            "and let the device charge for at least 30 minutes. If it still "
            "will not charge, reply with the device model, purchase or order "
            "details, and any indicator-light behavior so we can review the "
            "next support step."
        )
    if category == "warranty_replacement_inquiry":
        return (
            "Thanks for checking on warranty or replacement eligibility. I "
            "cannot confirm a warranty or replacement outcome from this draft. "
            f"Based on the cited support guidance I found ({source}), please "
            "send your order number, purchase date, product model, photos of "
            "the issue, and any troubleshooting already tried so a human "
            "reviewer can apply the policy."
        )
    if category == "returns_refunds_inquiry":
        return (
            "Thanks for asking about a return or refund. I cannot confirm a "
            "return or refund outcome from this draft. Based on the cited "
            f"support guidance I found ({source}), please share your order "
            "number, delivery date, item condition, and reason for the request "
            "so a human reviewer can apply the policy."
        )
    if category == "unknown_low_confidence":
        return (
            "Thanks for reaching out. I do not have enough cited context to "
            "give a reliable answer yet. Please share your order number or "
            "account email, the product or service involved, and what outcome "
            "you need so a human reviewer can continue safely."
        )
    return (
        "Thanks for the details. Based on the cited support guidance I found "
        f"({source}), please try restarting the device or app, checking the "
        "connection or power source, and noting any error message. If the "
        "issue continues, reply with the model, order details, and what "
        "changed before the issue started."
    )


def _recommended_actions(
    category: str,
) -> tuple[Mapping[str, Any], ...]:
    if category == "charging_issue":
        return (
            {
                "type": "customer_reply_draft",
                "label": "Share cited charging troubleshooting steps",
                "requires_execution": False,
            },
            {
                "type": "warranty_claim",
                "label": "Prepare a warranty claim for the charging issue",
                "requires_execution": True,
                "tool_name": "warranty.claim",
                "payload": {
                    "order_id": "unknown_order",
                    "product_sku": "unknown_sku",
                    "issue_category": "charging_issue",
                    "customer_description": "Charging issue reported by customer.",
                },
                "target_resource_id": "warranty:charging_issue",
            },
            {
                "type": "collect_context",
                "label": "Collect model, order details, and indicator behavior",
                "requires_execution": False,
            },
        )
    if category == "product_defect":
        return (
            {
                "type": "customer_reply_draft",
                "label": "Draft a grounded product-defect response",
                "requires_execution": False,
            },
            {
                "type": "warranty_claim",
                "label": "Prepare a warranty claim for the product defect",
                "requires_execution": True,
                "tool_name": "warranty.claim",
                "payload": {
                    "order_id": "unknown_order",
                    "product_sku": "unknown_sku",
                    "issue_category": "product_defect",
                    "customer_description": "Product defect reported by customer.",
                },
                "target_resource_id": "warranty:product_defect",
            },
            {
                "type": "warehouse_repair",
                "label": "Create a warehouse repair report for defect review",
                "requires_execution": True,
                "tool_name": "warehouse.repair.report",
                "payload": {
                    "product_sku": "unknown_sku",
                    "batch_id": None,
                    "defect_description": "Product defect reported by customer.",
                    "severity": "high",
                    "session_id": "unknown_session",
                },
                "target_resource_id": "warehouse:repair:product_defect",
            },
            {
                "type": "collect_context",
                "label": "Ask for model number and defect evidence",
                "requires_execution": False,
            },
        )
    if category == "refund_requested":
        return (
            {
                "type": "customer_reply_draft",
                "label": "Draft a grounded refund response",
                "requires_execution": False,
            },
            {
                "type": "refund_request",
                "label": "Prepare a refund request for policy review",
                "requires_execution": True,
                "tool_name": "refund.request",
                "payload": {
                    "order_id": "unknown_order",
                    "product_sku": "unknown_sku",
                    "refund_amount_cents": 5000,
                    "refund_reason": "Customer requested refund.",
                },
                "target_resource_id": "refund:requested",
            },
            {
                "type": "human_policy_review",
                "label": "Route refund for policy review when needed",
                "requires_execution": False,
            },
        )
    if category == "warranty_replacement_inquiry":
        return (
            {
                "type": "collect_context",
                "label": "Collect warranty eligibility details",
                "requires_execution": False,
            },
            {
                "type": "human_policy_review",
                "label": "Review replacement policy before any commitment",
                "requires_execution": False,
            },
        )
    if category == "returns_refunds_inquiry":
        return (
            {
                "type": "collect_context",
                "label": "Collect return or refund eligibility details",
                "requires_execution": False,
            },
            {
                "type": "human_policy_review",
                "label": "Review refund policy before any commitment",
                "requires_execution": False,
            },
        )
    return (
        {
            "type": "collect_context",
            "label": "Collect missing customer and product details",
            "requires_execution": False,
        },
    )


def _evaluate_gate(
    *,
    category: str,
    confidence: float,
    original_content: str,
    reply: str,
    evidence: tuple[Mapping[str, Any], ...],
    auto_approve_threshold: float,
) -> _GateDecision:
    reasons: list[str] = []
    text = f"{original_content} {reply}".lower()
    evidence_empty = len(evidence) == 0
    if evidence_empty:
        reasons.append("missing_citations")
    if confidence < auto_approve_threshold:
        reasons.append("low_confidence")
    if _contains_any(text, _SAFETY_KEYWORDS):
        reasons.append("safety_risk")
    if _contains_any(text, _LEGAL_KEYWORDS):
        reasons.append("legal_or_chargeback_risk")
    if _contains_any(text, _FRAUD_KEYWORDS):
        reasons.append("fraud_risk")
    if _contains_any(text, _POLICY_EXCEPTION_KEYWORDS):
        reasons.append("policy_exception")
    if _high_value_refund_or_replacement(text):
        reasons.append("high_value_refund_or_replacement")
    if _has_conflicting_evidence(evidence):
        reasons.append("conflicting_evidence")
    if _contains_any(reply.lower(), _UNSUPPORTED_PROMISE_PATTERNS):
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
    if reasons or category not in _SAFE_AUTO_CATEGORIES:
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


def _source_reference(evidence: tuple[Mapping[str, Any], ...]) -> str:
    titles = [
        str(item.get("title"))
        for item in evidence
        if isinstance(item.get("title"), str) and str(item.get("title")).strip()
    ]
    if not titles:
        return "cited support guidance"
    return "; ".join(titles[:2])


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


def _high_value_refund_or_replacement(text: str) -> bool:
    if not _contains_any(text, ("refund", "replacement", "replace", "warranty")):
        return False
    for match in _MONEY_PATTERN.finditer(text):
        amount_text = match.group("prefix") or match.group("suffix")
        if amount_text is None:
            continue
        amount = float(amount_text.replace(",", ""))
        if amount >= 100:
            return True
    return False


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug


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
