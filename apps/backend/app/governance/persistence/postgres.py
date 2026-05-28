"""Postgres implementation of ``BaseGovernanceRepository``.

Satisfies the Protocol in
``app/governance/persistence/repository.py`` with the same observable
semantics as :class:`InMemoryGovernanceRepository` — write-once
writes, tenant-scoped point reads, paginated queries clamped to the
caller's tenant.

The repository owns SQL only. Serialisation between record shapes
and ORM rows lives in this module too because the JSONB blobs carry
already-serialised dicts and the conversion is purely structural —
no semantic transformation occurs (that is the substrate's
serializer's job).

Tenant-scope semantics
----------------------

* Decisions / traces: own ``tenant_id`` column; clamp directly via
  :meth:`TenantScopedRepository._clamp_tenant`. NULL ``tenant_id``
  rows are invisible to any tenant-scoped read (NULL = $X is unknown
  in SQL three-valued logic, filtered out).
* Enforcement actions: no own ``tenant_id`` column; tenant scope
  inherits from the owning :class:`GovernanceDecisionRow`. The
  ``get_enforcement_actions`` method joins on the parent decision
  and applies the clamp there.

Write-once contract
-------------------

The substrate raises ``ValueError`` when a duplicate apex id is
written (matching the in-memory implementation). Postgres also
raises ``IntegrityError`` on the underlying PK / FK violation; the
repository converts the integrity error into a uniform
``ValueError`` so callers can branch on a single exception type
regardless of backend.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.governance.db.models import (
    EnforcementActionRow,
    GovernanceDecisionRow,
    GovernanceTraceRow,
)
from app.repositories.base import BaseRepository
from app.repositories.pagination import SERVER_PAGE_HARD_CAP, fetch_scalar_page
from app.governance.persistence.models import DecisionQuery, RecordPage
from app.governance.persistence.records import (
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PolicyEvaluationResultRecord,
    PolicyEvaluationTraceRecord,
    PolicyViolationRecord,
    RuntimeRestrictionRecord,
)


class PostgresGovernanceRepository(BaseRepository):
    """Postgres-backed governance persistence.

    Constructor receives the request-scoped ``AsyncSession`` via
    :class:`BaseRepository`. The repository never commits or rolls
    back — that is the service layer's responsibility, per the
    project-wide repository discipline.

    Note on the clamp helper: this substrate does NOT extend
    :class:`TenantScopedRepository` because governance permits
    nullable ``tenant_id`` (system-level decisions) while the
    shared ``_clamp_tenant`` helper is typed against
    ``TenantScopedMixin`` (which is NOT NULL by definition).
    The clamp predicate is therefore inlined below. SQL semantics
    are identical to the shared helper: ``WHERE tenant_id =
    $expected`` correctly excludes ``NULL`` via three-valued
    logic so tenantless rows remain invisible to a scoped reader.
    """

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_decision(
        self, record: GovernanceDecisionRecord
    ) -> None:
        row = GovernanceDecisionRow(
            decision_id=UUID(record.decision_id),
            decision=record.decision,
            stage=record.stage,
            policy_chain_id=record.policy_chain_id,
            reason=record.reason,
            decided_at=_iso_to_datetime(record.decided_at),
            correlation_id=record.correlation_id,
            request_id=record.request_id,
            tenant_id=record.tenant_id,
            subject_kind=record.subject_kind,
            governance_version=record.governance_version,
            violations=[v.to_dict() for v in record.violations],
            restrictions=[r.to_dict() for r in record.restrictions],
            evaluated_rules=[e.to_dict() for e in record.evaluated_rules],
            metadata_json=dict(record.metadata),
        )
        try:
            # SAVEPOINT-isolated insert: IntegrityError rolls back the
            # savepoint only, NOT the outer transaction the service
            # layer (or a test fixture) is managing.
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise ValueError(
                f"decision {record.decision_id!r} already recorded; "
                "records are write-once"
            ) from exc

    async def record_trace(
        self, record: GovernanceTraceRecord
    ) -> None:
        row = GovernanceTraceRow(
            decision_id=UUID(record.decision_id),
            request_id=record.request_id,
            correlation_id=record.correlation_id,
            stage=record.stage,
            action=record.action,
            resource=record.resource,
            actor=record.actor,
            tenant_id=record.tenant_id,
            subject_kind=record.subject_kind,
            started_at=_iso_to_datetime(record.started_at),
            ended_at=_iso_to_datetime(record.ended_at),
            latency_ms=record.latency_ms,
            status=record.status,
            final_decision=record.final_decision,
            policy_chain_id=record.policy_chain_id,
            rule_count=record.rule_count,
            violation_count=record.violation_count,
            restriction_count=record.restriction_count,
            enforcement_handler=record.enforcement_handler,
            enforcement_status=record.enforcement_status,
            enforcement_latency_ms=record.enforcement_latency_ms,
            error=record.error,
            policy_traces=[t.to_dict() for t in record.policy_traces],
            metadata_json=dict(record.metadata),
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise ValueError(
                f"trace for decision {record.decision_id!r} already "
                "recorded; records are write-once"
            ) from exc

    async def record_enforcement_action(
        self, record: EnforcementActionRecord
    ) -> None:
        row = EnforcementActionRow(
            action_id=UUID(record.action_id),
            decision_id=UUID(record.decision_id),
            handler_name=record.handler_name,
            outcome=record.outcome,
            applied_at=_iso_to_datetime(record.applied_at),
            detail=record.detail,
            metadata_json=dict(record.metadata),
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise ValueError(
                f"enforcement action {record.action_id!r} could not "
                "be recorded (duplicate id or unknown decision_id)"
            ) from exc

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_decision(
        self,
        decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> GovernanceDecisionRecord | None:
        stmt = select(GovernanceDecisionRow).where(
            GovernanceDecisionRow.decision_id == UUID(decision_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(
                GovernanceDecisionRow.tenant_id == expected_tenant_id
            )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _decision_row_to_record(row)

    async def get_trace(
        self,
        decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> GovernanceTraceRecord | None:
        stmt = select(GovernanceTraceRow).where(
            GovernanceTraceRow.decision_id == UUID(decision_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(
                GovernanceTraceRow.tenant_id == expected_tenant_id
            )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _trace_row_to_record(row)

    async def get_enforcement_actions(
        self,
        decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[EnforcementActionRecord, ...]:
        # Tenant scope inherits from the owning decision. Resolve
        # the parent first; if it is invisible from the requesting
        # tenant, return empty unconditionally — callers cannot
        # enumerate cross-tenant actions by guessing decision_ids.
        if expected_tenant_id is not None:
            owner_stmt = select(GovernanceDecisionRow.tenant_id).where(
                GovernanceDecisionRow.decision_id == UUID(decision_id)
            )
            owner_tenant = (
                await self.session.execute(owner_stmt)
            ).scalar_one_or_none()
            if owner_tenant != expected_tenant_id:
                return ()
        stmt = (
            select(EnforcementActionRow)
            .where(EnforcementActionRow.decision_id == UUID(decision_id))
            .order_by(EnforcementActionRow.applied_at)
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=SERVER_PAGE_HARD_CAP,
            offset=0,
        )
        return tuple(_action_row_to_record(r) for r in page.items)

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_decisions(
        self, query: DecisionQuery
    ) -> RecordPage[GovernanceDecisionRecord]:
        stmt: Select[tuple[GovernanceDecisionRow]] = select(GovernanceDecisionRow)
        stmt = _apply_decision_filters(stmt, query)
        stmt = stmt.order_by(GovernanceDecisionRow.decided_at)
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return RecordPage(
            items=tuple(_decision_row_to_record(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def query_traces(
        self, query: DecisionQuery
    ) -> RecordPage[GovernanceTraceRecord]:
        stmt: Select[tuple[GovernanceTraceRow]] = select(GovernanceTraceRow)
        stmt = _apply_trace_filters(stmt, query)
        stmt = stmt.order_by(GovernanceTraceRow.started_at)
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return RecordPage(
            items=tuple(_trace_row_to_record(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


# ─── Filter composers ────────────────────────────────────────────────────


def _apply_decision_filters(
    stmt: Select[tuple[GovernanceDecisionRow]],
    query: DecisionQuery,
) -> Select[tuple[GovernanceDecisionRow]]:
    """Apply every ``DecisionQuery`` field to a decisions ``Select``.

    Mirrors the in-memory ``_matches_decision`` predicate
    one-to-one. Substrate-wide consistency means a caller can swap
    backends without rewriting their query expectations.
    """
    if query.decision_id is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.decision_id == UUID(query.decision_id)
        )
    if query.correlation_id is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.correlation_id == query.correlation_id
        )
    if query.request_id is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.request_id == query.request_id
        )
    if query.tenant_id is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.tenant_id == query.tenant_id
        )
    if query.stage is not None:
        stmt = stmt.where(GovernanceDecisionRow.stage == query.stage)
    if query.policy_chain_id is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.policy_chain_id == query.policy_chain_id
        )
    if query.subject_kind is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.subject_kind == query.subject_kind
        )
    if query.final_decision is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.decision == query.final_decision
        )
    if query.decided_after_or_at is not None:
        stmt = stmt.where(
            GovernanceDecisionRow.decided_at >= query.decided_after_or_at
        )
    return stmt


def _apply_trace_filters(
    stmt: Select[tuple[GovernanceTraceRow]],
    query: DecisionQuery,
) -> Select[tuple[GovernanceTraceRow]]:
    """Mirrors the in-memory ``_matches_trace`` predicate."""
    if query.decision_id is not None:
        stmt = stmt.where(
            GovernanceTraceRow.decision_id == UUID(query.decision_id)
        )
    if query.correlation_id is not None:
        stmt = stmt.where(
            GovernanceTraceRow.correlation_id == query.correlation_id
        )
    if query.request_id is not None:
        stmt = stmt.where(
            GovernanceTraceRow.request_id == query.request_id
        )
    if query.tenant_id is not None:
        stmt = stmt.where(
            GovernanceTraceRow.tenant_id == query.tenant_id
        )
    if query.stage is not None:
        stmt = stmt.where(GovernanceTraceRow.stage == query.stage)
    if query.policy_chain_id is not None:
        stmt = stmt.where(
            GovernanceTraceRow.policy_chain_id == query.policy_chain_id
        )
    if query.subject_kind is not None:
        stmt = stmt.where(
            GovernanceTraceRow.subject_kind == query.subject_kind
        )
    if query.final_decision is not None:
        stmt = stmt.where(
            GovernanceTraceRow.final_decision == query.final_decision
        )
    return stmt


# ─── Row → record converters ─────────────────────────────────────────────


def _decision_row_to_record(
    row: GovernanceDecisionRow,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=str(row.decision_id),
        decision=row.decision,
        stage=row.stage,
        policy_chain_id=row.policy_chain_id,
        reason=row.reason,
        decided_at=row.decided_at.isoformat(),
        correlation_id=row.correlation_id,
        request_id=row.request_id,
        tenant_id=row.tenant_id,
        subject_kind=row.subject_kind,
        governance_version=row.governance_version,
        violations=tuple(
            PolicyViolationRecord.from_dict(v) for v in row.violations
        ),
        restrictions=tuple(
            RuntimeRestrictionRecord.from_dict(r)
            for r in row.restrictions
        ),
        evaluated_rules=tuple(
            PolicyEvaluationResultRecord.from_dict(e)
            for e in row.evaluated_rules
        ),
        metadata=dict(row.metadata_json),
    )


def _trace_row_to_record(
    row: GovernanceTraceRow,
) -> GovernanceTraceRecord:
    return GovernanceTraceRecord(
        decision_id=str(row.decision_id),
        request_id=row.request_id,
        correlation_id=row.correlation_id,
        stage=row.stage,
        action=row.action,
        resource=row.resource,
        actor=row.actor,
        tenant_id=row.tenant_id,
        subject_kind=row.subject_kind,
        started_at=row.started_at.isoformat(),
        ended_at=row.ended_at.isoformat(),
        latency_ms=row.latency_ms,
        status=row.status,
        final_decision=row.final_decision,
        policy_chain_id=row.policy_chain_id,
        rule_count=row.rule_count,
        violation_count=row.violation_count,
        restriction_count=row.restriction_count,
        enforcement_handler=row.enforcement_handler,
        enforcement_status=row.enforcement_status,
        enforcement_latency_ms=row.enforcement_latency_ms,
        policy_traces=tuple(
            PolicyEvaluationTraceRecord.from_dict(t)
            for t in row.policy_traces
        ),
        error=row.error,
        metadata=dict(row.metadata_json),
    )


def _action_row_to_record(
    row: EnforcementActionRow,
) -> EnforcementActionRecord:
    return EnforcementActionRecord(
        action_id=str(row.action_id),
        handler_name=row.handler_name,
        decision_id=str(row.decision_id),
        outcome=row.outcome,
        applied_at=row.applied_at.isoformat(),
        detail=row.detail,
        metadata=dict(row.metadata_json),
    )


# ─── ISO timestamp helper ────────────────────────────────────────────────


def _iso_to_datetime(iso: str):  # type: ignore[no-untyped-def]
    """Parse an ISO-8601 timestamp the record substrate emitted.

    Records store timestamps as ISO strings for JSON portability;
    the ORM column is ``TIMESTAMPTZ`` so we need a ``datetime``.
    ``datetime.fromisoformat`` accepts the substrate's emission
    format directly since Python 3.11+.
    """
    from datetime import datetime

    return datetime.fromisoformat(iso)


__all__ = ["PostgresGovernanceRepository"]
