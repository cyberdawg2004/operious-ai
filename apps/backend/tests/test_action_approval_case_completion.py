"""Break-controls for ActionApprovalService's case-completion hook.

One manager decision on a case-bound action must do both halves or
neither -- approving/denying via the standalone Action Approvals surface
must never leave a linked case (and its reply) untouched. These tests
exercise ActionApprovalService._complete_bound_case_if_any directly: the
single completion hook that approve_in_transaction/deny_in_transaction
both call after resolving the action, regardless of which surface
(Action Approvals tab vs the case-bound inline approve_case path) drove
the resolution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.approvals import ActionApprovalRecord, InMemoryActionApprovalRepository
from app.agents.tools.grants import AgentActionGrantRepository
from app.agents.tools.orchestration import ActionOrchestrationRuntime
from app.governance.persistence import InMemoryGovernanceRepository
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime.timeline_runtime import TimelineRuntime
from app.services.action_approval_service import ActionApprovalService
from app.session.persistence import InMemorySessionPersistence

_TENANT = "tenant-action-completion"


class _RecordingCaseCompleter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, datetime, str]] = []

    async def __call__(
        self,
        action_approval_id: str,
        tenant_id: str,
        action_status: str,
        resolved_by: str,
        resolved_at: datetime,
        resolution_note: str,
    ) -> object:
        self.calls.append(
            (
                action_approval_id,
                tenant_id,
                action_status,
                resolved_by,
                resolved_at,
                resolution_note,
            )
        )
        return None


def _resolved_record(*, status: str) -> ActionApprovalRecord:
    return ActionApprovalRecord(
        approval_id="action-approval-1",
        tenant_id=_TENANT,
        session_id="session-1",
        execution_id="execution-1",
        tool_name="warranty.claim",
        idempotency_key="idem-1",
        payload_json={},
        governance_decision_id=None,
        status=status,
        resolved_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        resolved_by="manager-jane",
        resolution_note="approved via action approvals tab",
    )


def _service(*, case_resolution_completer: _RecordingCaseCompleter | None) -> ActionApprovalService:
    session_repository = InMemorySessionPersistence()
    return ActionApprovalService(
        approval_repository=InMemoryActionApprovalRepository(),
        grant_repository=cast(AgentActionGrantRepository, object()),
        governance_repository=InMemoryGovernanceRepository(),
        resolution_repository=InMemoryResolutionProposalPersistence(),
        session_repository=session_repository,
        timeline_runtime=TimelineRuntime(persistence=session_repository),
        session=cast(AsyncSession, object()),
        orchestration_runtime=cast(ActionOrchestrationRuntime, object()),
        case_resolution_completer=case_resolution_completer,
    )


@pytest.mark.asyncio
async def test_approved_action_completion_calls_the_completer_with_real_args() -> None:
    completer = _RecordingCaseCompleter()
    service = _service(case_resolution_completer=completer)
    resolved = _resolved_record(status="approved")

    await service._complete_bound_case_if_any(resolved)

    assert completer.calls == [
        (
            "action-approval-1",
            _TENANT,
            "approved",
            "manager-jane",
            datetime(2026, 6, 24, tzinfo=timezone.utc),
            "approved via action approvals tab",
        )
    ]


@pytest.mark.asyncio
async def test_denied_action_completion_also_calls_the_completer() -> None:
    """A case-bound action denied via Action Approvals must also drive its
    case to rejected -- denial is a peer disposition, not a special case
    that's allowed to leave the case dangling."""
    completer = _RecordingCaseCompleter()
    service = _service(case_resolution_completer=completer)
    resolved = _resolved_record(status="denied")

    await service._complete_bound_case_if_any(resolved)

    assert len(completer.calls) == 1
    assert completer.calls[0][2] == "denied"


@pytest.mark.asyncio
async def test_no_completer_configured_is_a_safe_no_op() -> None:
    """Existing callers that never wire a completer (e.g. crisis-action
    approvals with no bound case) must be completely unaffected."""
    service = _service(case_resolution_completer=None)
    resolved = _resolved_record(status="approved")

    await service._complete_bound_case_if_any(resolved)  # must not raise


@pytest.mark.asyncio
async def test_unresolved_record_is_a_safe_no_op() -> None:
    """Defensive guard: a record missing resolved_at/resolved_by (should
    never happen for a just-resolved action) must not crash the caller."""
    completer = _RecordingCaseCompleter()
    service = _service(case_resolution_completer=completer)
    unresolved = ActionApprovalRecord(
        approval_id="action-approval-2",
        tenant_id=_TENANT,
        session_id="session-1",
        execution_id="execution-1",
        tool_name="warranty.claim",
        idempotency_key="idem-2",
        payload_json={},
        governance_decision_id=None,
        status="approved",
    )

    await service._complete_bound_case_if_any(unresolved)

    assert completer.calls == []
