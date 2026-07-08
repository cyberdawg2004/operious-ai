"""Manager Assistant Service — orchestrates the two-pass query pipeline.

Pass 1: LLM maps question → query_key + window_days (via agent.map_intent)
Pass 2: ManagerQueryRunner fetches real tenant-scoped data
Pass 3: LLM narrates the result (via agent.run / BaseGovernedLLMAgent)

Tenant isolation is STRUCTURAL: every query in ManagerQueryRunner takes
expected_tenant_id and enforces it at the data layer. The service passes
agent_input.tenant_id from the HTTP request — a manager for tenant A
cannot receive tenant B's data because no code path reaches across tenants.

Cross-tenant isolation invariant:
    query_runner.fetch(query_key, tenant_id, ...) ALWAYS passes
    expected_tenant_id=tenant_id to every underlying repository call.
    No query omits expected_tenant_id. This is tested in
    test_manager_assistant_cross_tenant_isolation.py.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from app.agents.tools.approvals import ActionApprovalRepository
from app.agents.governed.manager_assistant import (
    SAFE_QUERIES,
    ManagerAssistantAgent,
    cannot_answer_response,
)
from app.agents.governed.base import AgentInput
from app.agents.governed.proposal import AgentProposal, AgentProposalStatus
from app.approvals.persistence.models import CaseApprovalQuery
from app.approvals.persistence.repository import CaseApprovalPersistenceProtocol
from app.escalation.persistence.models import EscalationQuery
from app.escalation.persistence.repository import EscalationPersistenceProtocol
from app.observability.persistence.models import OperationalMetricsQuery
from app.observability.persistence.repository import OperationalObservabilityPersistence
from app.session.persistence import SessionPersistenceProtocol, SessionQuery
from app.tenant.persistence import TenantConfigurationRepository
from app.tenant.persistence.models import TenantKnowledgeDocumentQuery
from app.types.json import JsonArray, JsonValue

logger = logging.getLogger(__name__)
_VALID_MANAGER_QUERY_KEYS = frozenset(query.key for query in SAFE_QUERIES)


def _contradiction_count(metadata: dict[str, Any] | None) -> int:
    if metadata is None:
        return 0
    raw = metadata.get("contradiction_count", 0)
    return raw if isinstance(raw, int) else 0


def _contradiction_types(metadata: dict[str, Any] | None) -> JsonArray:
    if metadata is None:
        return []
    raw = metadata.get("contradiction_types", [])
    if not isinstance(raw, list):
        return []
    raw_values = cast(list[object], raw)
    typed_values: JsonArray = [value for value in raw_values if isinstance(value, str)]
    return typed_values


# ── Result contract ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    """Structured answer returned to the API layer."""

    answer: str
    chart_type: str  # "none" | "bar" | "number"
    chart_data: dict[str, Any]
    query_key: str
    cannot_answer: bool
    invocation_id: str


# ── Tenant-scoped query runner ────────────────────────────────────────────────


class ManagerQueryRunner:
    """Executes pre-defined, tenant-scoped data queries.

    Every method takes expected_tenant_id and passes it through to the
    repository. This is the structural tenant-isolation guarantee.
    """

    def __init__(
        self,
        *,
        observability_persistence: OperationalObservabilityPersistence,
        escalation_persistence: EscalationPersistenceProtocol,
        case_approval_persistence: CaseApprovalPersistenceProtocol,
        action_approval_persistence: ActionApprovalRepository,
        session_persistence: SessionPersistenceProtocol,
        tenant_config_repo: TenantConfigurationRepository,
    ) -> None:
        self._obs = observability_persistence
        self._esc = escalation_persistence
        self._case = case_approval_persistence
        self._action = action_approval_persistence
        self._sessions = session_persistence
        self._tenant_config = tenant_config_repo

    async def fetch(
        self,
        query_key: str,
        *,
        tenant_id: str,
        window_days: int = 7,
    ) -> dict[str, Any]:
        """Dispatch to the correct query. All branches pass tenant_id."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)

        if query_key == "auto_resolution_rate":
            return await self._auto_resolution_rate(
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=now,
                window_days=window_days,
            )
        if query_key == "ticket_volume":
            return await self._ticket_volume(
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=now,
                window_days=window_days,
            )
        if query_key == "pending_action_approvals":
            return await self._pending_action_approvals(tenant_id=tenant_id)
        if query_key == "pending_case_approvals":
            return await self._pending_case_approvals(tenant_id=tenant_id)
        if query_key == "escalation_rate":
            return await self._escalation_rate(
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=now,
                window_days=window_days,
            )
        if query_key == "governance_deny_rate":
            return await self._governance_deny_rate(
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=now,
                window_days=window_days,
            )
        if query_key == "qa_score":
            return await self._qa_score(
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=now,
                window_days=window_days,
            )
        if query_key == "sop_conflicts":
            return await self._sop_conflicts(tenant_id=tenant_id)
        if query_key == "open_escalations":
            return await self._open_escalations(tenant_id=tenant_id)
        if query_key == "avg_response_latency":
            return await self._avg_response_latency(
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=now,
                window_days=window_days,
            )
        if query_key == "active_sessions":
            return await self._active_sessions(tenant_id=tenant_id)
        if query_key == "top_issue_categories":
            return await self._top_issue_categories(
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=now,
                window_days=window_days,
            )
        return {"error": f"unknown query_key: {query_key!r}"}

    # ── Individual query implementations ─────────────────────────────────────

    async def _metrics(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> Any:
        return await self._obs.read_metrics(
            query=OperationalMetricsQuery(
                window_start=window_start,
                window_end=window_end,
            ),
            expected_tenant_id=tenant_id,
        )

    async def _auto_resolution_rate(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        window_days: int,
    ) -> dict[str, Any]:
        snap = await self._metrics(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
        total = snap.ticket_throughput
        escalations = snap.escalation_count
        auto_resolved = max(0, total - escalations)
        rate = (auto_resolved / total) if total > 0 else 0.0
        return {
            "query": "auto_resolution_rate",
            "window_days": window_days,
            "total_tickets": total,
            "auto_resolved": auto_resolved,
            "escalated": escalations,
            "auto_resolution_rate": round(rate, 4),
            "auto_resolution_rate_pct": round(rate * 100, 1),
        }

    async def _ticket_volume(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        window_days: int,
    ) -> dict[str, Any]:
        snap = await self._metrics(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
        return {
            "query": "ticket_volume",
            "window_days": window_days,
            "ticket_throughput": snap.ticket_throughput,
            "execution_count": snap.execution_count,
            "completed_execution_count": snap.completed_execution_count,
        }

    async def _pending_action_approvals(
        self, *, tenant_id: str
    ) -> dict[str, Any]:
        items = await self._action.list_approvals(
            expected_tenant_id=tenant_id,
            status="pending",
            limit=200,
            offset=0,
        )
        count = len(items)
        return {
            "query": "pending_action_approvals",
            "pending_count": count,
        }

    async def _pending_case_approvals(
        self, *, tenant_id: str
    ) -> dict[str, Any]:
        page = await self._case.list_cases(
            CaseApprovalQuery(
                tenant_id=tenant_id,
                status="pending_sme_review",
                limit=200,
                offset=0,
            ),
            expected_tenant_id=tenant_id,
        )
        return {
            "query": "pending_case_approvals",
            "pending_count": page.total,
        }

    async def _escalation_rate(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        window_days: int,
    ) -> dict[str, Any]:
        snap = await self._metrics(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
        return {
            "query": "escalation_rate",
            "window_days": window_days,
            "escalation_count": snap.escalation_count,
            "ticket_throughput": snap.ticket_throughput,
            "escalation_rate": round(snap.escalation_rate, 4),
            "escalation_rate_pct": round(snap.escalation_rate * 100, 1),
        }

    async def _governance_deny_rate(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        window_days: int,
    ) -> dict[str, Any]:
        snap = await self._metrics(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
        return {
            "query": "governance_deny_rate",
            "window_days": window_days,
            "governance_decision_count": snap.governance_decision_count,
            "governance_deny_count": snap.governance_deny_count,
            "governance_deny_rate": round(snap.governance_deny_rate, 4),
            "governance_deny_rate_pct": round(snap.governance_deny_rate * 100, 1),
        }

    async def _qa_score(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        window_days: int,
    ) -> dict[str, Any]:
        snap = await self._metrics(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
        return {
            "query": "qa_score",
            "window_days": window_days,
            "qa_score_count": snap.qa_score_count,
            "qa_score_average": (
                round(snap.qa_score_average, 3)
                if snap.qa_score_average is not None
                else None
            ),
            "qa_score_average_pct": (
                round(snap.qa_score_average * 100, 1)
                if snap.qa_score_average is not None
                else None
            ),
        }

    async def _sop_conflicts(self, *, tenant_id: str) -> dict[str, Any]:
        conflicts: list[dict[str, JsonValue]]
        try:
            from app.tenant.enums import TenantKnowledgeReviewStatus

            quarantined_page = await self._tenant_config.list_knowledge_documents(
                TenantKnowledgeDocumentQuery(
                    review_status=TenantKnowledgeReviewStatus.QUARANTINED,
                    limit=100,
                    offset=0,
                ),
                expected_tenant_id=tenant_id,
            )
            conflicts = []
            for doc in quarantined_page.items:
                metadata = doc.contradiction_metadata
                if not metadata or not metadata.get("contradiction_flagged"):
                    continue
                conflicts.append(
                    {
                        "document_id": str(doc.document_id),
                        "title": doc.title,
                        "contradiction_count": _contradiction_count(metadata),
                        "contradiction_types": _contradiction_types(metadata),
                    }
                )
        except Exception:
            logger.warning(
                "manager_assistant_sop_conflicts_fetch_failed tenant=%s", tenant_id,
                exc_info=True,
            )
            conflicts = []
        return {
            "query": "sop_conflicts",
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
        }

    async def _open_escalations(self, *, tenant_id: str) -> dict[str, Any]:
        page = await self._esc.list_escalations(
            EscalationQuery(tenant_id=tenant_id, status="pending", limit=100, offset=0),
            expected_tenant_id=tenant_id,
        )
        return {
            "query": "open_escalations",
            "open_count": page.total,
            "items": [
                {
                    "escalation_id": r.escalation_id,
                    "reason": r.reason,
                    "priority": r.priority,
                    "created_at": r.created_at,
                }
                for r in page.items[:10]
            ],
        }

    async def _avg_response_latency(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        window_days: int,
    ) -> dict[str, Any]:
        snap = await self._metrics(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
        return {
            "query": "avg_response_latency",
            "window_days": window_days,
            "latency_ms_avg": snap.execution_latency_ms_avg,
            "latency_ms_p50": snap.execution_latency_ms_p50,
            "latency_ms_p95": snap.execution_latency_ms_p95,
        }

    async def _active_sessions(self, *, tenant_id: str) -> dict[str, Any]:
        page = await self._sessions.list_sessions(
            SessionQuery(lifecycle_phase=None, limit=1, offset=0),
            expected_tenant_id=tenant_id,
        )
        active_page = await self._sessions.list_sessions(
            SessionQuery(
                lifecycle_phase=_active_phase(),
                limit=1,
                offset=0,
            ),
            expected_tenant_id=tenant_id,
        )
        return {
            "query": "active_sessions",
            "active_count": active_page.total,
            "total_count": page.total,
        }

    async def _top_issue_categories(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        window_days: int,
    ) -> dict[str, Any]:
        snap = await self._metrics(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
        # The metrics snapshot carries throughput; detailed category breakdown
        # is in supervisor inspection data (not queried here for latency reasons).
        return {
            "query": "top_issue_categories",
            "window_days": window_days,
            "total_tickets": snap.ticket_throughput,
            "note": (
                "Detailed per-category breakdown is available in the "
                "Quality Reviews section. Total ticket count shown here."
            ),
        }


def _active_phase() -> Any:
    """Return the SessionLifecyclePhase.ACTIVE value safely."""
    from app.session.enums import SessionLifecyclePhase
    return SessionLifecyclePhase.ACTIVE


# ── Service ───────────────────────────────────────────────────────────────────


class ManagerAssistantService:
    """Orchestrates the full question → query → answer pipeline.

    Tenant isolation is enforced at every layer:
    - agent.map_intent: tenant_id is passed to LLM for logging only (no data)
    - query_runner.fetch: EVERY call passes expected_tenant_id
    - agent.run: agent_input.tenant_id is propagated to governance + audit
    """

    def __init__(
        self,
        *,
        agent: ManagerAssistantAgent,
        query_runner: ManagerQueryRunner,
    ) -> None:
        self._agent = agent
        self._runner = query_runner

    async def answer(
        self,
        *,
        question: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> AssistantAnswer:
        """Full pipeline: intent map → data fetch → narration."""
        exec_id = str(uuid.uuid4())  # EPHEMERAL: request-scoped invocation ID
        sess_id = session_id or exec_id

        # Pass 1: intent mapping
        intent = await self._agent.map_intent(question=question, tenant_id=tenant_id)
        cannot_answer = bool(intent.get("cannot_answer", True))
        query_key = str(intent.get("query_key") or "")
        window_days = int(intent.get("window_days") or 7)

        if cannot_answer or query_key not in _VALID_MANAGER_QUERY_KEYS:
            resp = cannot_answer_response(question)
            return AssistantAnswer(
                answer=resp["answer"],
                chart_type="none",
                chart_data={},
                query_key="",
                cannot_answer=True,
                invocation_id=exec_id,
            )

        # Pass 2: tenant-scoped data fetch
        try:
            query_result = await self._runner.fetch(
                query_key,
                tenant_id=tenant_id,
                window_days=window_days,
            )
        except Exception:
            logger.warning(
                "manager_assistant_query_fetch_failed key=%s tenant=%s",
                query_key,
                tenant_id,
                exc_info=True,
            )
            return AssistantAnswer(
                answer=(
                    "I ran into an issue fetching that data right now. "
                    "Please try again in a moment."
                ),
                chart_type="none",
                chart_data={},
                query_key=query_key,
                cannot_answer=False,
                invocation_id=exec_id,
            )

        # Pass 3: narration via governed agent
        agent_input = AgentInput(
            tenant_id=tenant_id,
            session_id=sess_id,
            execution_id=exec_id,
            content={
                "question": question,
                "query_key": query_key,
                "window_days": window_days,
                "query_result": query_result,
            },
        )
        proposal: AgentProposal = await self._agent.run(agent_input)

        if proposal.status == AgentProposalStatus.COMPLETED and proposal.output:
            output = proposal.output
            return AssistantAnswer(
                answer=str(output.get("answer", "")),
                chart_type=str(output.get("chart_type", "none")),
                chart_data=dict(output.get("chart_data") or {}),
                query_key=query_key,
                cannot_answer=False,
                invocation_id=proposal.invocation_id,
            )

        # Agent failed / governance blocked — return the raw data at minimum
        label = next((q.label for q in SAFE_QUERIES if q.key == query_key), query_key)
        fallback = _format_fallback(label, query_result)
        return AssistantAnswer(
            answer=fallback,
            chart_type="none",
            chart_data={},
            query_key=query_key,
            cannot_answer=False,
            invocation_id=proposal.invocation_id,
        )


def _format_fallback(label: str, data: dict[str, Any]) -> str:
    """Minimal fallback when narration fails — just show the raw numbers."""
    lines = [f"**{label}**"]
    for k, v in data.items():
        if k in ("query",):
            continue
        lines.append(f"• {k}: {v}")
    return "\n".join(lines)


__all__ = [
    "AssistantAnswer",
    "ManagerAssistantService",
    "ManagerQueryRunner",
]
