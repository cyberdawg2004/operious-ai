"""Application service for SME-reviewed case approvals."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.enums import (
    CaseApprovalOutboxStatus,
    CaseApprovalStatus,
    TERMINAL_CASE_APPROVAL_STATUSES,
)
from app.approvals.exceptions import (
    CaseApprovalGuidanceRejectedError,
    CaseApprovalLifecycleError,
    CaseApprovalNotFoundError,
    CaseApprovalRuntimeError,
)
from app.approvals.identity import derive_approval_outbox_id
from app.approvals.persistence import (
    CaseApprovalOutboxRecord,
    CaseApprovalPersistenceProtocol,
    CaseApprovalQuery,
    CaseApprovalRecord,
)
from app.escalation.runtime import EscalationAgentRuntime
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import (
    BaseGovernanceRepository,
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PolicyEvaluationResultRecord,
)
from app.knowledge.poisoning import (
    KnowledgeInjectionScanner,
    PatternKnowledgeInjectionScanner,
)
from app.resolution.enums import (
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
)
from app.resolution.persistence import (
    ResolutionOutboundDraftPersistenceProtocol,
    ResolutionProposalPersistenceProtocol,
    ResolutionProposalRecord,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateProtocol,
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
)
from app.sme import SmeCaseContext, SmeReviewRuntime

# Verdicts under which a (possibly revised) resolution may be delivered after a
# human approval. ALLOW = clean pass; REQUIRE_APPROVAL = the gate defers to the
# human sign-off this surface provides. Any other verdict (DENY/ESCALATE/
# DEGRADE/REDACT) is a hard governance stop that a human approval cannot waive.
_DELIVERABLE_VERDICTS: frozenset[ResolutionGovernanceVerdict] = frozenset(
    {
        ResolutionGovernanceVerdict.ALLOW,
        ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
    }
)

_CASE_APPROVAL_NAMESPACE = uuid.UUID("51b3132f-2f18-4e68-a002-ef97051b0101")
_POLICY_VERSION = "fix_1b.case_approval.v1"
_APPROVE_CHAIN_ID = "case_approval.human_approve.v1"
_GUIDE_CHAIN_ID = "case_approval.operator_guidance.v1"
_ESCALATE_CHAIN_ID = "case_approval.operator_escalate.v1"
_REJECT_CHAIN_ID = "case_approval.human_reject.v1"

ActionApprovalApprove = Callable[
    [str, str, str | None, str, str],
    Awaitable[object],
]
ActionApprovalDeny = Callable[
    [str, str, str, str, str],
    Awaitable[object],
]
PostCommitFlush = Callable[[], Awaitable[None]]


class ResolutionApprovalPersistenceProtocol(
    ResolutionProposalPersistenceProtocol,
    ResolutionOutboundDraftPersistenceProtocol,
    Protocol,
):
    """Resolution persistence surface needed when a case is approved."""


class CaseApprovalService:
    """Command Center service for SME review and human sign-off."""

    def __init__(
        self,
        *,
        persistence: CaseApprovalPersistenceProtocol,
        sme_runtime: SmeReviewRuntime,
        resolution_repository: ResolutionApprovalPersistenceProtocol,
        governance_repository: BaseGovernanceRepository,
        session: AsyncSession | None = None,
        escalation_runtime: EscalationAgentRuntime | None = None,
        injection_scanner: KnowledgeInjectionScanner | None = None,
        action_approval_approve: ActionApprovalApprove | None = None,
        action_approval_deny: ActionApprovalDeny | None = None,
        resolution_governance_gate: ResolutionGovernanceGateProtocol | None = None,
        post_commit_flush: PostCommitFlush | None = None,
    ) -> None:
        self._persistence = persistence
        self._sme_runtime = sme_runtime
        self._resolutions = resolution_repository
        self._governance = governance_repository
        self._session = session
        self._escalation_runtime = escalation_runtime
        self._scanner = injection_scanner or PatternKnowledgeInjectionScanner()
        self._action_approval_approve = action_approval_approve
        self._action_approval_deny = action_approval_deny
        self._resolution_gate = resolution_governance_gate
        self._post_commit_flush = post_commit_flush

    async def list_cases(
        self,
        *,
        tenant_id: str,
        query: CaseApprovalQuery,
    ) -> tuple[CaseApprovalRecord, ...]:
        page = await self._persistence.list_cases(
            query,
            expected_tenant_id=tenant_id,
        )
        return page.items

    async def get_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
    ) -> CaseApprovalRecord | None:
        return await self._persistence.get_case(
            approval_case_id,
            expected_tenant_id=tenant_id,
        )

    async def review_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
        guidance: str | None = None,
    ) -> CaseApprovalRecord:
        record = await self._require_case(
            approval_case_id=approval_case_id,
            tenant_id=tenant_id,
        )
        if record.status not in {
            CaseApprovalStatus.PENDING_SME_REVIEW,
            CaseApprovalStatus.GUIDANCE_IN_PROGRESS,
        }:
            raise CaseApprovalLifecycleError(
                "SME review can only run for pending or guided cases"
            )
        proposal = await self._proposal_for_record(record)
        recommendation = await self._sme_runtime.review_case(
            _context_for_record(record, proposal=proposal),
            guidance=guidance,
            guidance_round=record.guidance_round,
        )
        updated = replace(
            record,
            status=CaseApprovalStatus.AWAITING_APPROVAL,
            sme_recommendation_id=recommendation.recommendation_id,
            recommended_action=(
                record.recommended_action
                or _first_fireable_action(recommendation.recommended_actions)
            ),
            metadata={
                **dict(record.metadata),
                "sme_recommendation": recommendation.to_dict(),
                "sme_recommendation_hash": _recommendation_hash(
                    recommendation.to_dict()
                ),
            },
        )
        saved = await self._persistence.update_case(
            updated,
            expected_tenant_id=tenant_id,
        )
        # Create-or-reset the outbox to PENDING so a guided re-review
        # re-notifies the operator queue about the revised recommendation
        # instead of silently reusing an already-published row.
        await self._persistence.republish_outbox(
            CaseApprovalOutboxRecord(
                outbox_id=str(
                    derive_approval_outbox_id(
                        approval_case_id=saved.approval_case_id
                    )
                ),
                approval_case_id=saved.approval_case_id,
                tenant_id=saved.tenant_id,
                status=CaseApprovalOutboxStatus.PENDING,
                created_at=datetime.now(timezone.utc),
                metadata={
                    "status": saved.status.value,
                    "sme_recommendation_id": saved.sme_recommendation_id,
                    "guidance_round": saved.guidance_round,
                },
            ),
            expected_tenant_id=tenant_id,
        )
        return saved

    async def guide_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
        guided_by: str,
        guidance: str,
    ) -> CaseApprovalRecord:
        try:
            record = await self._require_case(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            )
            if record.status is not CaseApprovalStatus.AWAITING_APPROVAL:
                raise CaseApprovalLifecycleError(
                    "only awaiting approval cases can receive guidance"
                )
            if record.guidance_round > 0:
                raise CaseApprovalLifecycleError(
                    "case approval guidance is limited to one round"
                )
            scan = self._scanner.scan(guidance)
            if scan.flagged:
                raise CaseApprovalGuidanceRejectedError(
                    "operator guidance matched injection controls"
                )
            decision_id = await self._record_case_governance_decision(
                record=record,
                actor=guided_by,
                decision=Decision.REQUIRE_APPROVAL,
                policy_chain_id=_GUIDE_CHAIN_ID,
                reason="operator_guidance_recorded",
                note=None,
            )
            guided = replace(
                record,
                status=CaseApprovalStatus.GUIDANCE_IN_PROGRESS,
                guidance_round=1,
                guidance_ref=guidance,
                governance_decision_id=decision_id,
                metadata={
                    **dict(record.metadata),
                    "guided_by": guided_by,
                    "guidance_decision_id": decision_id,
                    "guidance_scan": {
                        "flagged": False,
                        "categories": list(scan.categories),
                    },
                },
            )
            await self._persistence.update_case(
                guided,
                expected_tenant_id=tenant_id,
            )
            reviewed = await self.review_case(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
                guidance=guidance,
            )
            await self._commit()
            return reviewed
        except Exception:
            await self._rollback()
            raise

    async def approve_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
        approved_by: str,
        note: str | None,
    ) -> CaseApprovalRecord:
        try:
            record = await self._require_case(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            )
            if record.status is not CaseApprovalStatus.AWAITING_APPROVAL:
                raise CaseApprovalLifecycleError(
                    "only awaiting approval cases can be approved"
                )
            guided_by = _text(record.metadata.get("guided_by"))
            if guided_by is not None and guided_by == approved_by:
                raise CaseApprovalLifecycleError(
                    "guided cases require a different approver"
                )
            decision_id = await self._record_case_governance_decision(
                record=record,
                actor=approved_by,
                decision=Decision.ALLOW,
                policy_chain_id=_APPROVE_CHAIN_ID,
                reason="case_approval_approved",
                note=note,
            )
            # Deliver the approved recommendation as what proceeds: a reply
            # that differs from the agent's original is grounding-gated and
            # then superseded; an unchanged reply is the already-grounded
            # original. All mutations stay in the request transaction and
            # are committed exactly once below (fail-closed on any error).
            if record.resolution_proposal_id is not None:
                await self._deliver_resolution(
                    record=record,
                    tenant_id=tenant_id,
                    governance_decision_id=decision_id,
                )
            await self._approve_recommended_action_if_bound(
                record=record,
                approved_by=approved_by,
                note=note,
                tenant_id=tenant_id,
            )
            approved = replace(
                record,
                status=CaseApprovalStatus.APPROVED,
                governance_decision_id=decision_id,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=approved_by,
                resolution_note=note,
                metadata={
                    **dict(record.metadata),
                    "approved_by": approved_by,
                    "approved_recommendation_hash": _text(
                        record.metadata.get("sme_recommendation_hash")
                    ),
                },
            )
            saved = await self._persistence.update_case(
                approved,
                expected_tenant_id=tenant_id,
            )
            await self._commit()
            return saved
        except Exception:
            await self._rollback()
            raise

    async def reject_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
        rejected_by: str,
        reason: str | None,
    ) -> CaseApprovalRecord:
        """Record a terminal "no" — distinct from escalate (which hands the
        case to a DIFFERENT queue for further review). Never delivers the
        resolution's customer-facing reply and never fires a bound action;
        if one exists, it is explicitly DENIED so it cannot be approved
        through some other path later.
        """
        try:
            record = await self._require_case(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            )
            if record.status is not CaseApprovalStatus.AWAITING_APPROVAL:
                raise CaseApprovalLifecycleError(
                    "only awaiting approval cases can be rejected"
                )
            decision_id = await self._record_case_governance_decision(
                record=record,
                actor=rejected_by,
                decision=Decision.DENY,
                policy_chain_id=_REJECT_CHAIN_ID,
                reason="case_approval_rejected",
                note=reason,
            )
            await self._deny_recommended_action_if_bound(
                record=record,
                denied_by=rejected_by,
                reason=reason,
                tenant_id=tenant_id,
            )
            rejected = replace(
                record,
                status=CaseApprovalStatus.REJECTED,
                governance_decision_id=decision_id,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=rejected_by,
                resolution_note=reason,
                metadata={
                    **dict(record.metadata),
                    "rejected_by": rejected_by,
                },
            )
            saved = await self._persistence.update_case(
                rejected,
                expected_tenant_id=tenant_id,
            )
            await self._commit()
            return saved
        except Exception:
            await self._rollback()
            raise

    async def escalate_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
        escalated_by: str,
        reason: str,
    ) -> CaseApprovalRecord:
        try:
            record = await self._require_case(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            )
            if record.status in TERMINAL_CASE_APPROVAL_STATUSES:
                raise CaseApprovalLifecycleError(
                    "terminal approval cases cannot be escalated"
                )
            decision_id = await self._record_case_governance_decision(
                record=record,
                actor=escalated_by,
                decision=Decision.ESCALATE,
                policy_chain_id=_ESCALATE_CHAIN_ID,
                reason="case_approval_escalated",
                note=reason,
            )
            escalation_id: str | None = None
            if self._escalation_runtime is not None:
                if record.session_id is None:
                    raise CaseApprovalRuntimeError(
                        "approval escalation requires session lineage"
                    )
                escalation = (
                    await self._escalation_runtime.create_for_governance_escalation(
                        governance_decision_id=decision_id,
                        expected_tenant_id=tenant_id,
                        session_id=record.session_id,
                    )
                )
                escalation_id = escalation.escalation_id
            escalated = replace(
                record,
                status=CaseApprovalStatus.ESCALATED,
                governance_decision_id=decision_id,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=escalated_by,
                resolution_note=reason,
                metadata={
                    **dict(record.metadata),
                    "escalated_by": escalated_by,
                    "escalation_id": escalation_id,
                },
            )
            saved = await self._persistence.update_case(
                escalated,
                expected_tenant_id=tenant_id,
            )
            await self._commit()
            return saved
        except Exception:
            await self._rollback()
            raise

    async def _require_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
    ) -> CaseApprovalRecord:
        record = await self._persistence.get_case(
            approval_case_id,
            expected_tenant_id=tenant_id,
        )
        if record is None:
            raise CaseApprovalNotFoundError(
                f"unknown approval case: {approval_case_id}"
            )
        return record

    async def _proposal_for_record(
        self,
        record: CaseApprovalRecord,
    ) -> ResolutionProposalRecord | None:
        if record.resolution_proposal_id is None:
            return None
        return await self._resolutions.get_resolution_proposal(
            record.resolution_proposal_id,
            expected_tenant_id=record.tenant_id,
        )

    async def _deliver_resolution(
        self,
        *,
        record: CaseApprovalRecord,
        tenant_id: str,
        governance_decision_id: str,
    ) -> None:
        proposal_id = record.resolution_proposal_id
        if proposal_id is None:  # pragma: no cover - guarded by caller
            return
        proposal = await self._proposal_for_record(record)
        if proposal is None:
            raise CaseApprovalRuntimeError(
                "approved resolution proposal is missing"
            )
        decision_uuid = uuid.UUID(governance_decision_id)
        recommendation = _recommendation_from_metadata(record.metadata)
        new_reply = _recommended_reply(recommendation)
        delivered_decision_uuid = decision_uuid
        if (
            new_reply is not None
            and new_reply != proposal.proposed_customer_reply.strip()
        ):
            # A revised (guided/model-authored) reply must pass the SAME full
            # resolution governance gate (communication policy + grounding) the
            # original proposal passed before it can supersede it. Guidance can
            # steer, but it cannot waive governance. A hard stop -> fail closed.
            revalidation = await self._revalidate_resolution_governance(
                proposal=proposal,
                record=record,
                tenant_id=tenant_id,
                revised_reply=new_reply,
                recommendation=recommendation,
            )
            if revalidation.governance_decision_id is not None:
                delivered_decision_uuid = revalidation.governance_decision_id
            await self._resolutions.update_resolution_proposal_reply(
                proposal_id,
                expected_tenant_id=tenant_id,
                proposed_customer_reply=new_reply,
                governance_decision_id=delivered_decision_uuid,
            )
            await self._resolutions.update_resolution_outbound_draft_body_for_proposal(
                proposal_id,
                expected_tenant_id=tenant_id,
                draft_body=new_reply,
                draft_body_sha256=hashlib.sha256(
                    new_reply.encode("utf-8")
                ).hexdigest(),
                governance_decision_id=delivered_decision_uuid,
            )
        await self._resolutions.update_resolution_proposal_status(
            proposal_id,
            expected_tenant_id=tenant_id,
            status=ResolutionProposalStatus.SEND_ELIGIBLE,
            governance_decision_id=delivered_decision_uuid,
        )
        await self._resolutions.update_resolution_outbound_draft_status_for_proposal(
            proposal_id,
            expected_tenant_id=tenant_id,
            status=ResolutionOutboundDraftStatus.READY,
            governance_decision_id=delivered_decision_uuid,
        )

    async def _revalidate_resolution_governance(
        self,
        *,
        proposal: ResolutionProposalRecord,
        record: CaseApprovalRecord,
        tenant_id: str,
        revised_reply: str,
        recommendation: Mapping[str, Any] | None,
    ) -> ResolutionGovernanceGateResult:
        segments = _reply_segments(recommendation)
        if not segments:
            # No claim segments means grounding cannot be verified for the
            # revised text -> never deliver unverifiable customer prose.
            raise CaseApprovalRuntimeError(
                "a revised SME reply must carry grounding segments; "
                "escalate instead of delivering unverifiable text"
            )
        if self._resolution_gate is None:
            raise CaseApprovalRuntimeError(
                "resolution governance gate is not configured; cannot deliver "
                "a revised reply"
            )
        result = await self._resolution_gate.evaluate_resolution_proposal(
            ResolutionGovernanceGateRequest(
                proposal_id=proposal.proposal_id,
                tenant_id=tenant_id,
                session_id=proposal.session_id or record.session_id or "",
                execution_id=proposal.execution_id or record.execution_id or "",
                dispatch_id=proposal.dispatch_id,
                diagnostic_event_id=proposal.diagnostic_event_id,
                diagnostic_summary=(
                    record.issue_summary or proposal.resolution_category
                ),
                diagnostic_category=proposal.resolution_category,
                diagnostic_confidence=proposal.confidence,
                original_content=record.issue_summary or "",
                proposed_customer_reply=revised_reply,
                resolution_category=proposal.resolution_category,
                recommended_actions=tuple(proposal.recommended_actions),
                evidence=tuple(proposal.evidence),
                local_supervisor_verdict=proposal.supervisor_verdict,
                local_governance_verdict=proposal.governance_verdict,
                local_autonomy_decision=proposal.autonomy_decision,
                local_status=proposal.status,
                local_reasons=(),
                reply_segments=segments,
                source_language=proposal.source_language,
            )
        )
        if result.governance_verdict not in _DELIVERABLE_VERDICTS:
            raise CaseApprovalRuntimeError(
                "revised SME reply failed resolution governance "
                f"({result.governance_verdict.value}); escalate the case"
            )
        return result

    async def _approve_recommended_action_if_bound(
        self,
        *,
        record: CaseApprovalRecord,
        approved_by: str,
        note: str | None,
        tenant_id: str,
    ) -> bool:
        action = record.recommended_action
        if action is None or not _requires_execution(action):
            return False
        action_approval_id = _text(action.get("action_approval_id"))
        if action_approval_id is None:
            return False
        if self._action_approval_approve is None:
            # A case bound to a real side-effect must not be marked approved
            # while the action silently never fires. Fail closed.
            raise CaseApprovalRuntimeError(
                "approving an action-bound case requires the action "
                "approval executor to be configured"
            )
        # The executor shares this request transaction and does NOT commit;
        # approve_case owns the single commit so the case-approved row and
        # the fired action commit atomically.
        await self._action_approval_approve(
            action_approval_id,
            approved_by,
            note,
            tenant_id,
            tenant_id,
        )
        return True

    async def _deny_recommended_action_if_bound(
        self,
        *,
        record: CaseApprovalRecord,
        denied_by: str,
        reason: str | None,
        tenant_id: str,
    ) -> bool:
        action = record.recommended_action
        if action is None or not _requires_execution(action):
            return False
        action_approval_id = _text(action.get("action_approval_id"))
        if action_approval_id is None:
            return False
        if self._action_approval_deny is None:
            # Symmetric with the approve side: a case bound to a real
            # action must not be marked rejected while that action is left
            # dangling pending — it could still be approved through a
            # different path later. Fail closed.
            raise CaseApprovalRuntimeError(
                "rejecting an action-bound case requires the action "
                "approval denier to be configured"
            )
        denial_note = (reason or "").strip() or "Rejected via case approval review."
        await self._action_approval_deny(
            action_approval_id,
            denied_by,
            denial_note,
            tenant_id,
            tenant_id,
        )
        return True

    async def _record_case_governance_decision(
        self,
        *,
        record: CaseApprovalRecord,
        actor: str,
        decision: Decision,
        policy_chain_id: str,
        reason: str,
        note: str | None,
    ) -> str:
        decision_id = str(
            uuid.uuid5(
                _CASE_APPROVAL_NAMESPACE,
                (
                    f"{record.tenant_id}|{record.approval_case_id}|"
                    f"{policy_chain_id}|{actor}|{record.guidance_round}"
                ),
            )
        )
        existing = await self._governance.get_decision(
            decision_id,
            expected_tenant_id=record.tenant_id,
        )
        if existing is not None:
            return decision_id
        now = datetime.now(timezone.utc)
        metadata: dict[str, Any] = {
            "approval_case_id": record.approval_case_id,
            "entry_category": record.entry_category.value,
            "session_id": record.session_id,
            "execution_id": record.execution_id,
            "dispatch_id": record.dispatch_id,
            "resolution_proposal_id": record.resolution_proposal_id,
            "actor": actor,
            "note": note,
        }
        rule = PolicyEvaluationResultRecord(
            policy_name=policy_chain_id,
            rule_id=reason,
            decision=decision.value,
            severity=10,
            reason=reason,
            evaluated_at=now.isoformat(),
            metadata=metadata,
            policy_version=_POLICY_VERSION,
        )
        decision_record = GovernanceDecisionRecord(
            decision_id=decision_id,
            decision=decision.value,
            stage=EnforcementStage.PRE_EXECUTION.value,
            policy_chain_id=policy_chain_id,
            reason=reason,
            decided_at=now.isoformat(),
            correlation_id=record.dispatch_id or record.execution_id,
            request_id=f"case-approval:{record.approval_case_id}",
            tenant_id=record.tenant_id,
            subject_kind="case_approval",
            governance_version=_POLICY_VERSION,
            evaluated_rules=(rule,),
            metadata=metadata,
        )
        trace_record = GovernanceTraceRecord(
            decision_id=decision_id,
            request_id=decision_record.request_id,
            correlation_id=decision_record.correlation_id,
            stage=decision_record.stage,
            action="case_approval:transition",
            resource=f"case_approval:{record.approval_case_id}",
            actor=actor,
            tenant_id=record.tenant_id,
            subject_kind="case_approval",
            started_at=now.isoformat(),
            ended_at=now.isoformat(),
            latency_ms=0.0,
            status="ok",
            final_decision=decision.value,
            policy_chain_id=policy_chain_id,
            rule_count=1,
            violation_count=0 if decision is Decision.ALLOW else 1,
            restriction_count=0,
            enforcement_handler="case_approval_service",
            enforcement_status="recorded",
            enforcement_latency_ms=0.0,
            metadata=metadata,
        )
        action_record = EnforcementActionRecord(
            action_id=str(
                uuid.uuid5(
                    _CASE_APPROVAL_NAMESPACE,
                    f"action|{record.approval_case_id}|{decision_id}",
                )
            ),
            handler_name="case_approval_service",
            decision_id=decision_id,
            outcome="recorded",
            applied_at=now.isoformat(),
            detail=reason,
            metadata=metadata,
        )
        await self._governance.record_decision(decision_record)
        await self._governance.record_trace(trace_record)
        await self._governance.record_enforcement_action(action_record)
        return decision_id

    async def _commit(self) -> None:
        if self._session is not None:
            await self._session.commit()
        if self._post_commit_flush is not None:
            await self._post_commit_flush()

    async def _rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()


def _context_for_record(
    record: CaseApprovalRecord,
    *,
    proposal: ResolutionProposalRecord | None,
) -> SmeCaseContext:
    metadata = dict(record.metadata)
    if proposal is not None:
        metadata.setdefault("confidence", proposal.confidence)
    return SmeCaseContext(
        approval_case_id=record.approval_case_id,
        tenant_id=record.tenant_id,
        session_id=record.session_id,
        execution_id=record.execution_id,
        dispatch_id=record.dispatch_id,
        resolution_proposal_id=record.resolution_proposal_id,
        entry_category=record.entry_category.value,
        ticket_ref=record.ticket_ref,
        product=record.product,
        issue_summary=record.issue_summary
        or (proposal.resolution_category if proposal is not None else None),
        proposed_customer_reply=(
            proposal.proposed_customer_reply if proposal is not None else None
        ),
        recommended_actions=(
            tuple(proposal.recommended_actions) if proposal is not None else ()
        ),
        citations=tuple(proposal.evidence) if proposal is not None else (),
        metadata=metadata,
    )


def _first_fireable_action(
    actions: tuple[Mapping[str, Any], ...],
) -> Mapping[str, Any] | None:
    for action in actions:
        if _requires_execution(action):
            return dict(action)
    return None


def _requires_execution(action: Mapping[str, Any]) -> bool:
    return action.get("requires_execution") is True


def _recommendation_from_metadata(
    metadata: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    value = metadata.get("sme_recommendation")
    if isinstance(value, Mapping):
        return cast("Mapping[str, Any]", value)
    return None


def _recommended_reply(
    recommendation: Mapping[str, Any] | None,
) -> str | None:
    if recommendation is None:
        return None
    return _text(recommendation.get("recommended_reply"))


def _reply_segments(
    recommendation: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], ...]:
    if recommendation is None:
        return ()
    value = recommendation.get("reply_segments")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    segments: list[Mapping[str, Any]] = []
    for item in cast("Sequence[object]", value):
        if isinstance(item, Mapping):
            segments.append(dict(cast("Mapping[str, Any]", item)))
    return tuple(segments)


def _recommendation_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = ["CaseApprovalService"]
