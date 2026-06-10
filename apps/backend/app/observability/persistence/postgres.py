"""Postgres operational observability persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.boundary.db.models import (
    BoundaryIngressRow,
    EmailCustomerReplyDeliveryRow,
    IngressDispatchOutboxRow,
    OutboundSendOutboxRow,
    WhatsAppCustomerReplyDeliveryRow,
)
from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
)
from app.escalation.db.models import EscalationOutboxRow, EscalationRecordRow
from app.execution.db.models import ExecutionAttemptRow, ExecutionOutboxRow, ExecutionRow
from app.execution.enums import ExecutionState
from app.observability.db.models import (
    OperationalSLODefinitionRow,
    OperationalTraceSpanRow,
)
from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.identity import (
    OperationalSLODefinitionId,
    OperationalTraceSpanId,
)
from app.observability.persistence.models import (
    DeadLetterExecutionPage,
    DeadLetterExecutionQuery,
    InboundMessageTimelineLookup,
    InboundNormalizationDeadLetterPage,
    InboundNormalizationDeadLetterQuery,
    OperationalMetricsQuery,
    OperationalSLODefinitionPage,
    OperationalSLODefinitionQuery,
    OperationalTraceSpanPage,
    OperationalTraceSpanQuery,
    StuckExecutionAlertPage,
    StuckExecutionAlertQuery,
)
from app.observability.persistence.records import (
    DeadLetterExecutionRecord,
    InboundMessageTimelineRecord,
    InboundMessageTimelineStageRecord,
    InboundNormalizationDeadLetterRecord,
    OperationalMetricsSnapshotRecord,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanRecord,
    QAScoreBucketRecord,
    StuckExecutionAlertRecord,
)
from app.governance.db.models import GovernanceDecisionRow, GovernanceTraceRow
from app.qa.db.models import QAScoreRow
from app.repositories.base import BaseRepository
from app.repositories.pagination import count_matching_rows, fetch_scalar_page
from app.resolution.db.models import ResolutionOutboundDraftRow, ResolutionProposalRow
from app.runtime.db.models import DeadLetterTaskRow
from app.session.db.models import SessionRow
from app.tenant.db.models import TenantRow


class PostgresOperationalObservabilityPersistence(BaseRepository):
    """Postgres-backed tenant operational observability read/config store."""

    async def read_metrics(
        self,
        query: OperationalMetricsQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalMetricsSnapshotRecord:
        ticket_stmt = select(BoundaryIngressRow.ingress_id).where(
            BoundaryIngressRow.tenant_id == expected_tenant_id,
            BoundaryIngressRow.received_at >= query.window_start,
            BoundaryIngressRow.received_at < query.window_end,
            BoundaryIngressRow.normalization_status
            == BoundaryNormalizationStatus.OK.value,
            BoundaryIngressRow.replay_disposition
            == BoundaryReplayDisposition.NEW.value,
        )
        ticket_throughput = await count_matching_rows(
            self.session,
            ticket_stmt,
        )
        governance_count, governance_deny_count = (
            await self.session.execute(
                select(
                    func.count(GovernanceDecisionRow.decision_id),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    GovernanceDecisionRow.decision == "deny",
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    GovernanceDecisionRow.tenant_id == expected_tenant_id,
                    GovernanceDecisionRow.decided_at >= query.window_start,
                    GovernanceDecisionRow.decided_at < query.window_end,
                )
            )
        ).one()
        execution_count, completed_execution_count = (
            await self.session.execute(
                select(
                    func.count(ExecutionRow.execution_id),
                    func.coalesce(
                        func.sum(
                            case(
                                (ExecutionRow.completed_at.is_not(None), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    ExecutionRow.tenant_id == expected_tenant_id,
                    ExecutionRow.requested_at >= query.window_start,
                    ExecutionRow.requested_at < query.window_end,
                )
            )
        ).one()
        ended_at = func.coalesce(
            ExecutionRow.completed_at,
            ExecutionRow.failed_at,
        )
        latency_ms = func.extract(
            "epoch",
            ended_at - ExecutionRow.requested_at,
        ) * 1000.0
        latency_avg, latency_p50, latency_p95, latency_p99 = (
            await self.session.execute(
                select(
                    func.avg(latency_ms),
                    func.percentile_disc(0.50).within_group(latency_ms),
                    func.percentile_disc(0.95).within_group(latency_ms),
                    case(
                        (
                            func.count(latency_ms) >= 100,
                            func.percentile_disc(0.99).within_group(latency_ms),
                        ),
                        else_=None,
                    ),
                ).where(
                    ExecutionRow.tenant_id == expected_tenant_id,
                    ExecutionRow.requested_at >= query.window_start,
                    ExecutionRow.requested_at < query.window_end,
                    ended_at.is_not(None),
                )
            )
        ).one()
        score = func.least(func.greatest(QAScoreRow.overall_score, 0.0), 1.0)
        qa_row = (
            await self.session.execute(
                select(
                    func.count(QAScoreRow.score_id),
                    func.avg(QAScoreRow.overall_score),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.0) & (score < 0.2), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.2) & (score < 0.4), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.4) & (score < 0.6), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(((score >= 0.6) & (score < 0.8), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((score >= 0.8, 1), else_=0)),
                        0,
                    ),
                ).where(
                    QAScoreRow.tenant_id == expected_tenant_id,
                    QAScoreRow.scored_at >= query.window_start,
                    QAScoreRow.scored_at < query.window_end,
                )
            )
        ).one()
        escalation_count = await count_matching_rows(
            self.session,
            select(EscalationRecordRow.escalation_id).where(
                EscalationRecordRow.tenant_id == expected_tenant_id,
                EscalationRecordRow.created_at >= query.window_start,
                EscalationRecordRow.created_at < query.window_end,
            ),
        )
        dlq_count = await count_matching_rows(
            self.session,
            select(ExecutionRow.execution_id).where(
                ExecutionRow.tenant_id == expected_tenant_id,
                ExecutionRow.state == ExecutionState.DEAD_LETTERED.value,
                ExecutionRow.failed_at.is_not(None),
                ExecutionRow.failed_at >= query.window_start,
                ExecutionRow.failed_at < query.window_end,
            ),
        )
        qa_count = int(qa_row[0] or 0)
        qa_average = _optional_float(qa_row[1])
        qa_distribution = (
            QAScoreBucketRecord(0.0, 0.2, int(qa_row[2] or 0)),
            QAScoreBucketRecord(0.2, 0.4, int(qa_row[3] or 0)),
            QAScoreBucketRecord(0.4, 0.6, int(qa_row[4] or 0)),
            QAScoreBucketRecord(0.6, 0.8, int(qa_row[5] or 0)),
            QAScoreBucketRecord(0.8, 1.0, int(qa_row[6] or 0)),
        )
        return OperationalMetricsSnapshotRecord(
            tenant_id=expected_tenant_id,
            window_start=query.window_start,
            window_end=query.window_end,
            ticket_throughput=ticket_throughput,
            governance_decision_count=int(governance_count or 0),
            governance_deny_count=int(governance_deny_count or 0),
            governance_deny_rate=_rate(
                int(governance_deny_count or 0),
                int(governance_count or 0),
            ),
            execution_count=int(execution_count or 0),
            completed_execution_count=int(completed_execution_count or 0),
            execution_latency_ms_avg=_optional_float(latency_avg),
            execution_latency_ms_p50=_optional_float(latency_p50),
            execution_latency_ms_p95=_optional_float(latency_p95),
            execution_latency_ms_p99=_optional_float(latency_p99),
            qa_score_count=qa_count,
            qa_score_average=qa_average,
            qa_score_distribution=qa_distribution,
            escalation_count=escalation_count,
            escalation_rate=_rate(escalation_count, ticket_throughput),
            dlq_count=dlq_count,
        )

    async def list_dead_letter_executions(
        self,
        query: DeadLetterExecutionQuery,
        *,
        expected_tenant_id: str,
    ) -> DeadLetterExecutionPage:
        stmt = select(ExecutionRow).where(
            ExecutionRow.tenant_id == expected_tenant_id,
            ExecutionRow.state == ExecutionState.DEAD_LETTERED.value,
        )
        if query.execution_id is not None:
            stmt = stmt.where(ExecutionRow.execution_id == query.execution_id)
        stmt = stmt.order_by(
            ExecutionRow.failed_at.desc(),
            ExecutionRow.requested_at.desc(),
            ExecutionRow.execution_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return DeadLetterExecutionPage(
            items=tuple(_dead_letter_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_stuck_execution_alerts(
        self,
        query: StuckExecutionAlertQuery,
        *,
        expected_tenant_id: str,
    ) -> StuckExecutionAlertPage:
        stmt = (
            select(ExecutionRow)
            .where(
                ExecutionRow.tenant_id == expected_tenant_id,
                ExecutionRow.state == ExecutionState.CLAIMED.value,
                ExecutionRow.claimed_at.is_not(None),
                ExecutionRow.claimed_at <= query.claimed_before_or_at,
            )
            .order_by(ExecutionRow.claimed_at, ExecutionRow.execution_id)
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return StuckExecutionAlertPage(
            items=tuple(
                _stuck_alert_row_to_record(
                    row,
                    claimed_before_or_at=query.claimed_before_or_at,
                )
                for row in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_inbound_normalization_dead_letters(
        self,
        query: InboundNormalizationDeadLetterQuery,
        *,
        expected_tenant_id: str,
    ) -> InboundNormalizationDeadLetterPage:
        stmt = select(BoundaryIngressRow).where(
            BoundaryIngressRow.tenant_id == expected_tenant_id,
            BoundaryIngressRow.normalization_status
            != BoundaryNormalizationStatus.OK.value,
            BoundaryIngressRow.error.is_not(None),
        )
        if query.normalization_status is not None:
            stmt = stmt.where(
                BoundaryIngressRow.normalization_status
                == query.normalization_status
            )
        stmt = stmt.order_by(
            BoundaryIngressRow.received_at.desc(),
            BoundaryIngressRow.ingress_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return InboundNormalizationDeadLetterPage(
            items=tuple(
                _inbound_dead_letter_row_to_record(row) for row in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def get_inbound_message_timeline(
        self,
        lookup: InboundMessageTimelineLookup,
        *,
        expected_tenant_id: str,
        stall_threshold_seconds: int,
        now: datetime | None = None,
    ) -> InboundMessageTimelineRecord:
        generated_at = _utc(now)
        ids = _TimelineIds()
        ids.set(lookup.key, lookup.value)

        ingress = await self._timeline_ingress(lookup, expected_tenant_id, ids)
        outbox = None
        session = await self._timeline_session(lookup, expected_tenant_id, ids)
        execution = await self._timeline_execution(lookup, expected_tenant_id, ids)
        proposal = await self._timeline_proposal(lookup, expected_tenant_id, ids)
        draft = await self._timeline_draft(lookup, expected_tenant_id, ids)
        outbound = await self._timeline_outbound_send(
            lookup,
            expected_tenant_id,
            ids,
        )

        _merge_ids_from_outbound(ids, outbound)
        _merge_ids_from_draft(ids, draft)
        _merge_ids_from_proposal(ids, proposal)
        _merge_ids_from_execution(ids, execution)
        _merge_ids_from_session(ids, session)
        _merge_ids_from_ingress(ids, ingress)

        if ingress is None and ids.ingress_id is not None:
            ingress = await self._get_ingress_by_id(ids.ingress_id, expected_tenant_id)
            _merge_ids_from_ingress(ids, ingress)
        if session is None:
            session = await self._session_from_ids(ids, expected_tenant_id)
            _merge_ids_from_session(ids, session)
        if execution is None:
            execution = await self._execution_from_ids(ids, expected_tenant_id)
            _merge_ids_from_execution(ids, execution)
        if proposal is None:
            proposal = await self._proposal_from_ids(ids, expected_tenant_id)
            _merge_ids_from_proposal(ids, proposal)
        if draft is None:
            draft = await self._draft_from_ids(ids, expected_tenant_id)
            _merge_ids_from_draft(ids, draft)
        if outbound is None:
            outbound = await self._outbound_from_ids(ids, expected_tenant_id)
            _merge_ids_from_outbound(ids, outbound)
        if ingress is None:
            ingress = await self._ingress_from_ids(ids, expected_tenant_id)
            _merge_ids_from_ingress(ids, ingress)
        if outbox is None and ids.ingress_id is not None:
            outbox = await self._dispatch_outbox_for_ingress(
                ids.ingress_id,
                expected_tenant_id,
            )

        governance = await self._governance_decision_from_ids(
            ids,
            expected_tenant_id,
        )
        governance_trace = await self._governance_trace_from_decision(
            ids.governance_decision_id,
            expected_tenant_id,
        )
        escalation = await self._escalation_from_ids(ids, expected_tenant_id)
        escalation_outbox = await self._escalation_outbox_from_escalation(
            escalation,
            expected_tenant_id,
        )
        email_delivery = await self._email_delivery_from_ids(ids, expected_tenant_id)
        whatsapp_delivery = await self._whatsapp_delivery_from_ids(
            ids,
            expected_tenant_id,
        )
        dead_letter = await self._dead_letter_from_ids(
            ids,
            execution,
            outbound,
            expected_tenant_id,
        )
        execution_attempts = await self._execution_attempts_from_ids(
            ids,
            expected_tenant_id,
        )
        execution_outbox = await self._execution_outbox_from_ids(
            ids,
            expected_tenant_id,
        )

        stages = _build_timeline_stages(
            ids=ids,
            ingress=ingress,
            dispatch_outbox=outbox,
            session=session,
            execution=execution,
            execution_attempts=execution_attempts,
            execution_outbox=execution_outbox,
            proposal=proposal,
            draft=draft,
            governance=governance,
            governance_trace=governance_trace,
            outbound=outbound,
            email_delivery=email_delivery,
            whatsapp_delivery=whatsapp_delivery,
            escalation=escalation,
            escalation_outbox=escalation_outbox,
            dead_letter=dead_letter,
        )
        terminal = _timeline_is_terminal(stages, ingress=ingress)
        latest = max((stage.occurred_at for stage in stages), default=None)
        stalled, stalled_reason = _timeline_stall_status(
            stages=stages,
            ingress=ingress,
            dispatch_outbox=outbox,
            execution=execution,
            proposal=proposal,
            draft=draft,
            governance=governance,
            outbound=outbound,
            terminal=terminal,
            latest_event_at=latest,
            now=generated_at,
            stall_threshold_seconds=stall_threshold_seconds,
        )
        current_stage = stages[-1].stage if stages else None
        response_ids = ids.as_metadata() if stages else _TimelineIds().as_metadata()
        return InboundMessageTimelineRecord(
            tenant_id=expected_tenant_id,
            lookup_key=lookup.key,
            lookup_value=lookup.value,
            ids=response_ids,
            stages=stages,
            current_stage=current_stage,
            terminal=terminal,
            stalled=stalled,
            stalled_reason=stalled_reason,
            stall_threshold_seconds=stall_threshold_seconds,
            latest_event_at=latest,
            generated_at=generated_at,
        )

    async def save_slo_definition(
        self,
        record: OperationalSLODefinitionRecord,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        await self._ensure_tenant(expected_tenant_id)
        existing = await self._slo_row(record.slo_id, expected_tenant_id)
        try:
            async with self.session.begin_nested():
                if existing is None:
                    self.session.add(_slo_record_to_row(record))
                else:
                    await self.session.execute(
                        update(OperationalSLODefinitionRow)
                        .where(
                            OperationalSLODefinitionRow.slo_id == record.slo_id,
                            OperationalSLODefinitionRow.tenant_id
                            == expected_tenant_id,
                        )
                        .values(
                            threshold_operator=record.threshold_operator.value,
                            threshold_value=record.threshold_value,
                            enabled=record.enabled,
                            updated_at=record.updated_at,
                            metadata_json=dict(record.metadata),
                        )
                    )
        except IntegrityError:
            existing = await self._slo_row(record.slo_id, expected_tenant_id)
            if existing is not None:
                return _slo_row_to_record(existing)
            raise
        stored = await self._slo_row(record.slo_id, expected_tenant_id)
        return record if stored is None else _slo_row_to_record(stored)

    async def get_slo_definition(
        self,
        slo_id: OperationalSLODefinitionId,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRecord | None:
        row = await self._slo_row(slo_id, expected_tenant_id)
        return None if row is None else _slo_row_to_record(row)

    async def list_slo_definitions(
        self,
        query: OperationalSLODefinitionQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionPage:
        stmt = select(OperationalSLODefinitionRow).where(
            OperationalSLODefinitionRow.tenant_id == expected_tenant_id
        )
        if query.slo_id is not None:
            stmt = stmt.where(OperationalSLODefinitionRow.slo_id == query.slo_id)
        if query.metric_name is not None:
            stmt = stmt.where(
                OperationalSLODefinitionRow.metric_name == query.metric_name.value
            )
        if query.enabled is not None:
            stmt = stmt.where(OperationalSLODefinitionRow.enabled == query.enabled)
        stmt = stmt.order_by(
            OperationalSLODefinitionRow.metric_name,
            OperationalSLODefinitionRow.window_minutes,
            OperationalSLODefinitionRow.severity,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return OperationalSLODefinitionPage(
            items=tuple(_slo_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def save_trace_span(
        self,
        record: OperationalTraceSpanRecord,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        await self._ensure_tenant(expected_tenant_id)
        try:
            async with self.session.begin_nested():
                self.session.add(_trace_span_record_to_row(record))
        except IntegrityError:
            existing = await self._trace_span_row(
                record.span_id,
                expected_tenant_id,
            )
            if existing is not None:
                return _trace_span_row_to_record(existing)
            raise
        return record

    async def get_trace_span(
        self,
        span_id: OperationalTraceSpanId,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRecord | None:
        row = await self._trace_span_row(span_id, expected_tenant_id)
        return None if row is None else _trace_span_row_to_record(row)

    async def list_trace_spans(
        self,
        query: OperationalTraceSpanQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanPage:
        stmt = select(OperationalTraceSpanRow).where(
            OperationalTraceSpanRow.tenant_id == expected_tenant_id
        )
        if query.span_id is not None:
            stmt = stmt.where(OperationalTraceSpanRow.span_id == query.span_id)
        if query.trace_id is not None:
            stmt = stmt.where(OperationalTraceSpanRow.trace_id == query.trace_id)
        stmt = stmt.order_by(
            OperationalTraceSpanRow.started_at,
            OperationalTraceSpanRow.span_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return OperationalTraceSpanPage(
            items=tuple(_trace_span_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def _timeline_ingress(
        self,
        lookup: InboundMessageTimelineLookup,
        expected_tenant_id: str,
        ids: "_TimelineIds",
    ) -> BoundaryIngressRow | None:
        if lookup.ingress_id is not None:
            return await self._get_ingress_by_id(lookup.ingress_id, expected_tenant_id)
        if lookup.external_conversation_id is not None:
            eligible_ingress_rank = case(
                (
                    (
                        BoundaryIngressRow.replay_disposition
                        == BoundaryReplayDisposition.NEW.value
                    )
                    & (
                        BoundaryIngressRow.normalization_status
                        == BoundaryNormalizationStatus.OK.value
                    ),
                    0,
                ),
                else_=1,
            )
            stmt = (
                select(BoundaryIngressRow)
                .where(
                    BoundaryIngressRow.tenant_id == expected_tenant_id,
                    BoundaryIngressRow.external_conversation_id
                    == lookup.external_conversation_id,
                )
                .order_by(
                    eligible_ingress_rank,
                    BoundaryIngressRow.received_at.desc(),
                    BoundaryIngressRow.ingress_id,
                )
                .limit(1)
            )
            return (await self.session.execute(stmt)).scalar_one_or_none()
        if ids.ingress_id is not None:
            return await self._get_ingress_by_id(ids.ingress_id, expected_tenant_id)
        return None

    async def _get_ingress_by_id(
        self,
        ingress_id: str,
        expected_tenant_id: str,
    ) -> BoundaryIngressRow | None:
        parsed = _optional_uuid(ingress_id)
        if parsed is None:
            return None
        stmt = select(BoundaryIngressRow).where(
            BoundaryIngressRow.ingress_id == parsed,
            BoundaryIngressRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _dispatch_outbox_for_ingress(
        self,
        ingress_id: str,
        expected_tenant_id: str,
    ) -> IngressDispatchOutboxRow | None:
        parsed = _optional_uuid(ingress_id)
        if parsed is None:
            return None
        stmt = select(IngressDispatchOutboxRow).where(
            IngressDispatchOutboxRow.ingress_id == parsed,
            IngressDispatchOutboxRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _timeline_session(
        self,
        lookup: InboundMessageTimelineLookup,
        expected_tenant_id: str,
        ids: "_TimelineIds",
    ) -> SessionRow | None:
        session_id = lookup.session_id or ids.session_id
        if session_id is None:
            return None
        parsed = _optional_uuid(session_id)
        if parsed is None:
            return None
        stmt = select(SessionRow).where(
            SessionRow.session_id == parsed,
            SessionRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _session_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> SessionRow | None:
        if ids.session_id is not None:
            found = await self._timeline_session(
                InboundMessageTimelineLookup(session_id=ids.session_id),
                expected_tenant_id,
                ids,
            )
            if found is not None:
                return found
        handles = [
            value
            for value in (ids.external_conversation_id, ids.ingress_id)
            if value is not None
        ]
        if not handles:
            return None
        stmt = (
            select(SessionRow)
            .where(
                SessionRow.tenant_id == expected_tenant_id,
                SessionRow.external_handle.in_(handles),
            )
            .order_by(SessionRow.opened_at, SessionRow.session_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _timeline_execution(
        self,
        lookup: InboundMessageTimelineLookup,
        expected_tenant_id: str,
        ids: "_TimelineIds",
    ) -> ExecutionRow | None:
        execution_id = lookup.execution_id or ids.execution_id
        if execution_id is None:
            return None
        parsed = _optional_uuid(execution_id)
        if parsed is None:
            return None
        stmt = select(ExecutionRow).where(
            ExecutionRow.execution_id == parsed,
            ExecutionRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _execution_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> ExecutionRow | None:
        filters: list[Any] = []
        if ids.execution_id is not None:
            parsed = _optional_uuid(ids.execution_id)
            if parsed is not None:
                filters.append(ExecutionRow.execution_id == parsed)
        if ids.session_id is not None:
            filters.append(ExecutionRow.session_id == ids.session_id)
        if ids.dispatch_id is not None:
            filters.append(ExecutionRow.dispatch_id == ids.dispatch_id)
        if not filters:
            return None
        stmt = (
            select(ExecutionRow)
            .where(ExecutionRow.tenant_id == expected_tenant_id, or_(*filters))
            .order_by(ExecutionRow.requested_at, ExecutionRow.execution_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _execution_attempts_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> tuple[ExecutionAttemptRow, ...]:
        if ids.execution_id is None:
            return ()
        parsed = _optional_uuid(ids.execution_id)
        if parsed is None:
            return ()
        stmt = (
            select(ExecutionAttemptRow)
            .join(ExecutionRow, ExecutionRow.execution_id == ExecutionAttemptRow.execution_id)
            .where(
                ExecutionAttemptRow.execution_id == parsed,
                ExecutionRow.tenant_id == expected_tenant_id,
            )
            .order_by(ExecutionAttemptRow.started_at, ExecutionAttemptRow.attempt_number)
            .limit(25)
        )
        return tuple((await self.session.execute(stmt)).scalars())

    async def _execution_outbox_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> ExecutionOutboxRow | None:
        if ids.execution_id is None:
            return None
        parsed = _optional_uuid(ids.execution_id)
        if parsed is None:
            return None
        stmt = (
            select(ExecutionOutboxRow)
            .join(ExecutionRow, ExecutionRow.execution_id == ExecutionOutboxRow.execution_id)
            .where(
                ExecutionOutboxRow.execution_id == parsed,
                ExecutionRow.tenant_id == expected_tenant_id,
            )
            .order_by(ExecutionOutboxRow.created_at, ExecutionOutboxRow.outbox_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _timeline_proposal(
        self,
        lookup: InboundMessageTimelineLookup,
        expected_tenant_id: str,
        ids: "_TimelineIds",
    ) -> ResolutionProposalRow | None:
        del lookup
        return await self._proposal_from_ids(ids, expected_tenant_id)

    async def _proposal_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> ResolutionProposalRow | None:
        filters: list[Any] = []
        if ids.proposal_id is not None:
            parsed = _optional_uuid(ids.proposal_id)
            if parsed is not None:
                filters.append(ResolutionProposalRow.proposal_id == parsed)
        if ids.execution_id is not None:
            parsed = _optional_uuid(ids.execution_id)
            if parsed is not None:
                filters.append(ResolutionProposalRow.execution_id == parsed)
        if ids.session_id is not None:
            parsed = _optional_uuid(ids.session_id)
            if parsed is not None:
                filters.append(ResolutionProposalRow.session_id == parsed)
        if not filters:
            return None
        stmt = (
            select(ResolutionProposalRow)
            .where(
                ResolutionProposalRow.tenant_id == expected_tenant_id,
                or_(*filters),
            )
            .order_by(
                ResolutionProposalRow.created_at,
                ResolutionProposalRow.proposal_id,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _timeline_draft(
        self,
        lookup: InboundMessageTimelineLookup,
        expected_tenant_id: str,
        ids: "_TimelineIds",
    ) -> ResolutionOutboundDraftRow | None:
        draft_id = lookup.draft_id or ids.draft_id
        if draft_id is not None:
            parsed = _optional_uuid(draft_id)
            if parsed is not None:
                stmt = select(ResolutionOutboundDraftRow).where(
                    ResolutionOutboundDraftRow.draft_id == parsed,
                    ResolutionOutboundDraftRow.tenant_id == expected_tenant_id,
                )
                return (await self.session.execute(stmt)).scalar_one_or_none()
        return await self._draft_from_ids(ids, expected_tenant_id)

    async def _draft_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRow | None:
        filters: list[Any] = []
        if ids.draft_id is not None:
            parsed = _optional_uuid(ids.draft_id)
            if parsed is not None:
                filters.append(ResolutionOutboundDraftRow.draft_id == parsed)
        if ids.proposal_id is not None:
            parsed = _optional_uuid(ids.proposal_id)
            if parsed is not None:
                filters.append(ResolutionOutboundDraftRow.proposal_id == parsed)
        if ids.execution_id is not None:
            filters.append(ResolutionOutboundDraftRow.execution_id == ids.execution_id)
        if ids.session_id is not None:
            filters.append(ResolutionOutboundDraftRow.session_id == ids.session_id)
        if not filters:
            return None
        stmt = (
            select(ResolutionOutboundDraftRow)
            .where(
                ResolutionOutboundDraftRow.tenant_id == expected_tenant_id,
                or_(*filters),
            )
            .order_by(
                ResolutionOutboundDraftRow.created_at,
                ResolutionOutboundDraftRow.draft_id,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _timeline_outbound_send(
        self,
        lookup: InboundMessageTimelineLookup,
        expected_tenant_id: str,
        ids: "_TimelineIds",
    ) -> OutboundSendOutboxRow | None:
        outbox_id = lookup.outbound_send_outbox_id or ids.outbound_send_outbox_id
        if outbox_id is None:
            return None
        parsed = _optional_uuid(outbox_id)
        if parsed is None:
            return None
        stmt = select(OutboundSendOutboxRow).where(
            OutboundSendOutboxRow.outbox_id == parsed,
            OutboundSendOutboxRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _outbound_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> OutboundSendOutboxRow | None:
        filters: list[Any] = []
        if ids.outbound_send_outbox_id is not None:
            parsed = _optional_uuid(ids.outbound_send_outbox_id)
            if parsed is not None:
                filters.append(OutboundSendOutboxRow.outbox_id == parsed)
        if ids.draft_id is not None:
            parsed = _optional_uuid(ids.draft_id)
            if parsed is not None:
                filters.append(OutboundSendOutboxRow.draft_id == parsed)
        if ids.proposal_id is not None:
            parsed = _optional_uuid(ids.proposal_id)
            if parsed is not None:
                filters.append(OutboundSendOutboxRow.proposal_id == parsed)
        if ids.session_id is not None:
            filters.append(OutboundSendOutboxRow.session_id == ids.session_id)
        if not filters:
            return None
        stmt = (
            select(OutboundSendOutboxRow)
            .where(
                OutboundSendOutboxRow.tenant_id == expected_tenant_id,
                or_(*filters),
            )
            .order_by(OutboundSendOutboxRow.created_at, OutboundSendOutboxRow.outbox_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _ingress_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> BoundaryIngressRow | None:
        if ids.ingress_id is not None:
            found = await self._get_ingress_by_id(ids.ingress_id, expected_tenant_id)
            if found is not None:
                return found
        if ids.external_conversation_id is None:
            return None
        return await self._timeline_ingress(
            InboundMessageTimelineLookup(
                external_conversation_id=ids.external_conversation_id
            ),
            expected_tenant_id,
            ids,
        )

    async def _governance_decision_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> GovernanceDecisionRow | None:
        if ids.governance_decision_id is None:
            return None
        parsed = _optional_uuid(ids.governance_decision_id)
        if parsed is None:
            return None
        stmt = select(GovernanceDecisionRow).where(
            GovernanceDecisionRow.decision_id == parsed,
            GovernanceDecisionRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _governance_trace_from_decision(
        self,
        governance_decision_id: str | None,
        expected_tenant_id: str,
    ) -> GovernanceTraceRow | None:
        if governance_decision_id is None:
            return None
        parsed = _optional_uuid(governance_decision_id)
        if parsed is None:
            return None
        stmt = select(GovernanceTraceRow).where(
            GovernanceTraceRow.decision_id == parsed,
            GovernanceTraceRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _escalation_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> EscalationRecordRow | None:
        filters: list[Any] = []
        if ids.governance_decision_id is not None:
            parsed = _optional_uuid(ids.governance_decision_id)
            if parsed is not None:
                filters.append(EscalationRecordRow.governance_decision_id == parsed)
        if ids.session_id is not None:
            parsed = _optional_uuid(ids.session_id)
            if parsed is not None:
                filters.append(EscalationRecordRow.session_id == parsed)
        if not filters:
            return None
        stmt = (
            select(EscalationRecordRow)
            .where(EscalationRecordRow.tenant_id == expected_tenant_id, or_(*filters))
            .order_by(EscalationRecordRow.created_at, EscalationRecordRow.escalation_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _escalation_outbox_from_escalation(
        self,
        escalation: EscalationRecordRow | None,
        expected_tenant_id: str,
    ) -> EscalationOutboxRow | None:
        if escalation is None:
            return None
        stmt = select(EscalationOutboxRow).where(
            EscalationOutboxRow.escalation_id == escalation.escalation_id,
            EscalationOutboxRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _email_delivery_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> EmailCustomerReplyDeliveryRow | None:
        filters: list[Any] = []
        if ids.draft_id is not None:
            parsed = _optional_uuid(ids.draft_id)
            if parsed is not None:
                filters.append(EmailCustomerReplyDeliveryRow.draft_id == parsed)
        if ids.governance_decision_id is not None:
            parsed = _optional_uuid(ids.governance_decision_id)
            if parsed is not None:
                filters.append(
                    EmailCustomerReplyDeliveryRow.governance_decision_id == parsed
                )
        if not filters:
            return None
        stmt = (
            select(EmailCustomerReplyDeliveryRow)
            .where(
                EmailCustomerReplyDeliveryRow.tenant_id == expected_tenant_id,
                *filters,
            )
            .order_by(
                EmailCustomerReplyDeliveryRow.created_at,
                EmailCustomerReplyDeliveryRow.delivery_id,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _whatsapp_delivery_from_ids(
        self,
        ids: "_TimelineIds",
        expected_tenant_id: str,
    ) -> WhatsAppCustomerReplyDeliveryRow | None:
        filters: list[Any] = []
        if ids.draft_id is not None:
            parsed = _optional_uuid(ids.draft_id)
            if parsed is not None:
                filters.append(WhatsAppCustomerReplyDeliveryRow.draft_id == parsed)
        if ids.governance_decision_id is not None:
            parsed = _optional_uuid(ids.governance_decision_id)
            if parsed is not None:
                filters.append(
                    WhatsAppCustomerReplyDeliveryRow.governance_decision_id == parsed
                )
        if not filters:
            return None
        stmt = (
            select(WhatsAppCustomerReplyDeliveryRow)
            .where(
                WhatsAppCustomerReplyDeliveryRow.tenant_id == expected_tenant_id,
                *filters,
            )
            .order_by(
                WhatsAppCustomerReplyDeliveryRow.created_at,
                WhatsAppCustomerReplyDeliveryRow.delivery_id,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _dead_letter_from_ids(
        self,
        ids: "_TimelineIds",
        execution: ExecutionRow | None,
        outbound: OutboundSendOutboxRow | None,
        expected_tenant_id: str,
    ) -> DeadLetterTaskRow | None:
        filters: list[Any] = []
        if execution is not None:
            filters.append(DeadLetterTaskRow.execution_id == execution.execution_id)
        if outbound is not None:
            filters.append(DeadLetterTaskRow.task_id == str(outbound.outbox_id))
        if ids.outbound_send_outbox_id is not None:
            filters.append(DeadLetterTaskRow.task_id == ids.outbound_send_outbox_id)
        if not filters:
            return None
        stmt = (
            select(DeadLetterTaskRow)
            .where(DeadLetterTaskRow.tenant_id == expected_tenant_id, or_(*filters))
            .order_by(DeadLetterTaskRow.created_at.desc(), DeadLetterTaskRow.dead_letter_task_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _ensure_tenant(self, tenant_id: str) -> None:
        await self.session.merge(TenantRow(tenant_id=tenant_id))

    async def _slo_row(
        self,
        slo_id: OperationalSLODefinitionId,
        expected_tenant_id: str,
    ) -> OperationalSLODefinitionRow | None:
        stmt = select(OperationalSLODefinitionRow).where(
            OperationalSLODefinitionRow.slo_id == slo_id,
            OperationalSLODefinitionRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _trace_span_row(
        self,
        span_id: OperationalTraceSpanId,
        expected_tenant_id: str,
    ) -> OperationalTraceSpanRow | None:
        stmt = select(OperationalTraceSpanRow).where(
            OperationalTraceSpanRow.span_id == span_id,
            OperationalTraceSpanRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class _TimelineIds:
    def __init__(self) -> None:
        self.ingress_id: str | None = None
        self.external_conversation_id: str | None = None
        self.session_id: str | None = None
        self.execution_id: str | None = None
        self.dispatch_id: str | None = None
        self.proposal_id: str | None = None
        self.draft_id: str | None = None
        self.governance_decision_id: str | None = None
        self.outbound_send_outbox_id: str | None = None

    def set(self, key: str, value: str | None) -> None:
        if value is None:
            return
        if hasattr(self, key):
            setattr(self, key, value)

    def as_metadata(self) -> dict[str, str | None]:
        return {
            "ingress_id": self.ingress_id,
            "external_conversation_id": self.external_conversation_id,
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "dispatch_id": self.dispatch_id,
            "proposal_id": self.proposal_id,
            "draft_id": self.draft_id,
            "governance_decision_id": self.governance_decision_id,
            "outbound_send_outbox_id": self.outbound_send_outbox_id,
        }


def _merge_ids_from_ingress(
    ids: _TimelineIds,
    row: BoundaryIngressRow | None,
) -> None:
    if row is None:
        return
    ids.ingress_id = str(row.ingress_id)
    if row.external_conversation_id:
        ids.external_conversation_id = row.external_conversation_id


def _merge_ids_from_session(ids: _TimelineIds, row: SessionRow | None) -> None:
    if row is None:
        return
    ids.session_id = str(row.session_id)
    if row.external_handle and ids.external_conversation_id is None:
        ids.external_conversation_id = row.external_handle
    metadata = dict(row.metadata_json or {})
    ids.ingress_id = ids.ingress_id or _metadata_text(metadata, "boundary.ingress_id")
    ids.dispatch_id = ids.dispatch_id or _metadata_text(
        metadata,
        "coordination.dispatch_id",
    )


def _merge_ids_from_execution(
    ids: _TimelineIds,
    row: ExecutionRow | None,
) -> None:
    if row is None:
        return
    ids.execution_id = str(row.execution_id)
    ids.session_id = ids.session_id or row.session_id
    ids.dispatch_id = ids.dispatch_id or row.dispatch_id
    ids.ingress_id = ids.ingress_id or _metadata_text(
        dict(row.metadata_json or {}),
        "boundary.ingress_id",
    )


def _merge_ids_from_proposal(
    ids: _TimelineIds,
    row: ResolutionProposalRow | None,
) -> None:
    if row is None:
        return
    ids.proposal_id = str(row.proposal_id)
    ids.session_id = ids.session_id or _uuid_text(row.session_id)
    ids.execution_id = ids.execution_id or _uuid_text(row.execution_id)
    ids.dispatch_id = ids.dispatch_id or str(row.dispatch_id)
    ids.governance_decision_id = ids.governance_decision_id or _uuid_text(
        row.governance_decision_id
    )


def _merge_ids_from_draft(
    ids: _TimelineIds,
    row: ResolutionOutboundDraftRow | None,
) -> None:
    if row is None:
        return
    ids.draft_id = str(row.draft_id)
    ids.proposal_id = ids.proposal_id or str(row.proposal_id)
    ids.session_id = ids.session_id or row.session_id
    ids.execution_id = ids.execution_id or row.execution_id
    ids.dispatch_id = ids.dispatch_id or row.dispatch_id
    ids.governance_decision_id = ids.governance_decision_id or _uuid_text(
        row.governance_decision_id
    )


def _merge_ids_from_outbound(
    ids: _TimelineIds,
    row: OutboundSendOutboxRow | None,
) -> None:
    if row is None:
        return
    ids.outbound_send_outbox_id = str(row.outbox_id)
    ids.draft_id = ids.draft_id or str(row.draft_id)
    ids.proposal_id = ids.proposal_id or str(row.proposal_id)
    ids.session_id = ids.session_id or row.session_id
    ids.dispatch_id = ids.dispatch_id or row.dispatch_id
    ids.governance_decision_id = ids.governance_decision_id or str(
        row.governance_decision_id
    )


def _build_timeline_stages(
    *,
    ids: _TimelineIds,
    ingress: BoundaryIngressRow | None,
    dispatch_outbox: IngressDispatchOutboxRow | None,
    session: SessionRow | None,
    execution: ExecutionRow | None,
    execution_attempts: tuple[ExecutionAttemptRow, ...],
    execution_outbox: ExecutionOutboxRow | None,
    proposal: ResolutionProposalRow | None,
    draft: ResolutionOutboundDraftRow | None,
    governance: GovernanceDecisionRow | None,
    governance_trace: GovernanceTraceRow | None,
    outbound: OutboundSendOutboxRow | None,
    email_delivery: EmailCustomerReplyDeliveryRow | None,
    whatsapp_delivery: WhatsAppCustomerReplyDeliveryRow | None,
    escalation: EscalationRecordRow | None,
    escalation_outbox: EscalationOutboxRow | None,
    dead_letter: DeadLetterTaskRow | None,
) -> tuple[InboundMessageTimelineStageRecord, ...]:
    stages: list[InboundMessageTimelineStageRecord] = []
    id_map = ids.as_metadata()
    if ingress is not None:
        stages.append(
            _stage_record(
                stage="INGRESSED",
                status=ingress.replay_disposition,
                occurred_at=ingress.received_at,
                source_table="boundary_ingress",
                source_id=str(ingress.ingress_id),
                ids=id_map,
                metadata={
                    "source_type": ingress.source_type,
                    "source_id": ingress.source_id,
                    "external_message_id": ingress.external_message_id,
                    "external_conversation_id": ingress.external_conversation_id,
                    "normalization_status": ingress.normalization_status,
                    "message_type": ingress.message_type,
                    "replay_disposition": ingress.replay_disposition,
                    **_sanitize_metadata(dict(ingress.metadata_json or {})),
                },
            )
        )
    if dispatch_outbox is not None:
        if dispatch_outbox.status == "dispatched":
            stages.append(
                _stage_record(
                    stage="ADMITTED",
                    status="admitted",
                    occurred_at=dispatch_outbox.created_at,
                    source_table="ingress_dispatch_outbox",
                    source_id=str(dispatch_outbox.outbox_id),
                    ids=id_map,
                    metadata=_dispatch_outbox_metadata(dispatch_outbox),
                )
            )
            stages.append(
                _stage_record(
                    stage="DISPATCHED",
                    status="dispatched",
                    occurred_at=dispatch_outbox.dispatched_at
                    or dispatch_outbox.created_at,
                    source_table="ingress_dispatch_outbox",
                    source_id=str(dispatch_outbox.outbox_id),
                    ids=id_map,
                    metadata=_dispatch_outbox_metadata(dispatch_outbox),
                )
            )
        elif dispatch_outbox.status == "dead_lettered":
            stages.append(
                _stage_record(
                    stage="DEAD_LETTERED",
                    status="dead_lettered",
                    occurred_at=dispatch_outbox.dispatched_at
                    or dispatch_outbox.claimed_at
                    or dispatch_outbox.created_at,
                    source_table="ingress_dispatch_outbox",
                    source_id=str(dispatch_outbox.outbox_id),
                    ids=id_map,
                    metadata={
                        **_dispatch_outbox_metadata(dispatch_outbox),
                        "reason": dispatch_outbox.last_error
                        or "ingress dispatch dead-lettered",
                    },
                )
            )
        else:
            stages.append(
                _stage_record(
                    stage="DISPATCH_DEFERRED",
                    status=dispatch_outbox.status,
                    occurred_at=dispatch_outbox.claimed_at
                    or dispatch_outbox.created_at,
                    source_table="ingress_dispatch_outbox",
                    source_id=str(dispatch_outbox.outbox_id),
                    ids=id_map,
                    metadata=_dispatch_outbox_metadata(dispatch_outbox),
                )
            )
    if session is not None:
        linked = session.parent_session_id is not None or _metadata_text(
            dict(session.metadata_json or {}),
            "case_continuity.mode",
        ) in {"continued", "reopened", "linked"}
        stages.append(
            _stage_record(
                stage="SESSION_LINKED" if linked else "SESSION_CREATED",
                status=session.lifecycle_phase,
                occurred_at=session.opened_at,
                source_table="operational_sessions",
                source_id=str(session.session_id),
                ids=id_map,
                metadata={
                    "external_handle": session.external_handle,
                    "lifecycle_phase": session.lifecycle_phase,
                    "lineage_depth": session.lineage_depth,
                    **_sanitize_metadata(dict(session.metadata_json or {})),
                },
            )
        )
    if execution is not None:
        stages.append(
            _stage_record(
                stage="EXECUTION_STARTED",
                status=execution.state,
                occurred_at=execution.requested_at,
                source_table="execution_records",
                source_id=str(execution.execution_id),
                ids=id_map,
                metadata={
                    "kind": execution.kind,
                    "state": execution.state,
                    "attempt_count": execution.attempt_count,
                    "execution_outbox_state": (
                        execution_outbox.state if execution_outbox is not None else None
                    ),
                    "attempt_states": [
                        attempt.state for attempt in execution_attempts
                    ],
                },
            )
        )
        if execution.state == "failed":
            stages.append(
                _stage_record(
                    stage="FAILED",
                    status="failed",
                    occurred_at=execution.failed_at or execution.requested_at,
                    source_table="execution_records",
                    source_id=str(execution.execution_id),
                    ids=id_map,
                    metadata={"reason": execution.error or "execution failed"},
                )
            )
        if execution.state == "dead_lettered":
            stages.append(
                _stage_record(
                    stage="DEAD_LETTERED",
                    status="dead_lettered",
                    occurred_at=execution.failed_at or execution.requested_at,
                    source_table="execution_records",
                    source_id=str(execution.execution_id),
                    ids=id_map,
                    metadata={"reason": execution.error or "execution dead-lettered"},
                )
            )
    if proposal is not None or draft is not None:
        if proposal is not None:
            proposal_stage_status = proposal.status
            proposal_stage_at = proposal.created_at
            proposal_source_table = "resolution_proposals"
            proposal_source_id = str(proposal.proposal_id)
            resolution_category = proposal.resolution_category
        else:
            assert draft is not None
            proposal_stage_status = draft.status
            proposal_stage_at = draft.created_at
            proposal_source_table = "resolution_outbound_drafts"
            proposal_source_id = str(draft.draft_id)
            resolution_category = draft.resolution_category
        stages.append(
            _stage_record(
                stage="PROPOSAL_CREATED",
                status=proposal_stage_status,
                occurred_at=proposal_stage_at,
                source_table=proposal_source_table,
                source_id=proposal_source_id,
                ids=id_map,
                metadata={
                    "proposal_status": (
                        proposal.status if proposal is not None else None
                    ),
                    "draft_status": draft.status if draft is not None else None,
                    "draft_body_sha256": (
                        draft.draft_body_sha256 if draft is not None else None
                    ),
                    "resolution_category": resolution_category,
                    "send_eligible": _proposal_send_eligible(proposal, governance),
                },
            )
        )
    if governance is not None:
        trace_metadata = (
            {
                "trace_status": governance_trace.status,
                "trace_latency_ms": governance_trace.latency_ms,
            }
            if governance_trace is not None
            else {}
        )
        stages.append(
            _stage_record(
                stage="GOVERNANCE_DECIDED",
                status=governance.decision,
                occurred_at=governance.decided_at,
                source_table="governance_decisions",
                source_id=str(governance.decision_id),
                ids=id_map,
                metadata={
                    "decision": governance.decision,
                    "stage": governance.stage,
                    "policy_chain_id": governance.policy_chain_id,
                    "reason": governance.reason,
                    "subject_kind": governance.subject_kind,
                    **trace_metadata,
                    **_sanitize_metadata(dict(governance.metadata_json or {})),
                },
            )
        )
    if outbound is not None:
        stages.append(
            _stage_record(
                stage="SEND_QUEUED",
                status=outbound.status,
                occurred_at=outbound.created_at,
                source_table="outbound_send_outbox",
                source_id=str(outbound.outbox_id),
                ids=id_map,
                metadata={
                    "channel": outbound.channel,
                    "action": outbound.action,
                    "recipient": outbound.recipient,
                    "draft_body_sha256": outbound.draft_body_sha256,
                    "attempt_count": outbound.attempt_count,
                    "next_attempt_at": _iso_or_none(outbound.next_attempt_at),
                    "last_error": outbound.last_error,
                    **_sanitize_metadata(dict(outbound.metadata_json or {})),
                },
            )
        )
        if outbound.status == "sent":
            provider_message_id = (
                _delivery_provider_message_id(email_delivery, whatsapp_delivery)
                or outbound.provider_message_id
            )
            stages.append(
                _stage_record(
                    stage="SENT",
                    status="sent",
                    occurred_at=_delivery_sent_at(email_delivery, whatsapp_delivery)
                    or outbound.sent_at
                    or outbound.updated_at,
                    source_table="outbound_send_outbox",
                    source_id=str(outbound.outbox_id),
                    ids=id_map,
                    metadata={
                        "provider_message_id": provider_message_id,
                        "channel": outbound.channel,
                        "recipient": outbound.recipient,
                    },
                )
            )
        if outbound.status == "dead_lettered":
            stages.append(
                _stage_record(
                    stage="DEAD_LETTERED",
                    status="dead_lettered",
                    occurred_at=outbound.updated_at,
                    source_table="outbound_send_outbox",
                    source_id=str(outbound.outbox_id),
                    ids=id_map,
                    metadata={
                        "reason": outbound.last_error
                        or (dead_letter.reason if dead_letter is not None else None)
                        or "outbound send dead-lettered",
                        "dead_letter_task_id": (
                            str(dead_letter.dead_letter_task_id)
                            if dead_letter is not None
                            else None
                        ),
                        "replay_state": (
                            dead_letter.replay_state
                            if dead_letter is not None
                            else None
                        ),
                    },
                )
            )
    if escalation is not None:
        stages.append(
            _stage_record(
                stage="ESCALATED",
                status=escalation.status,
                occurred_at=escalation.created_at,
                source_table="escalation_records",
                source_id=str(escalation.escalation_id),
                ids=id_map,
                metadata={
                    "reason": escalation.reason,
                    "handoff_kind": escalation.handoff_kind,
                    "priority": escalation.priority,
                    "outbox_status": (
                        escalation_outbox.status
                        if escalation_outbox is not None
                        else None
                    ),
                },
            )
        )
    return _dedupe_and_sort_stages(stages)


def _stage_record(
    *,
    stage: str,
    status: str,
    occurred_at: datetime,
    source_table: str,
    source_id: str,
    ids: dict[str, str | None],
    metadata: dict[str, Any],
) -> InboundMessageTimelineStageRecord:
    return InboundMessageTimelineStageRecord(
        stage=stage,
        status=status,
        occurred_at=_utc(occurred_at),
        source_table=source_table,
        source_id=source_id,
        ids={key: value for key, value in ids.items() if value is not None},
        metadata=_compact_metadata(_sanitize_metadata(metadata)),
    )


def _dispatch_outbox_metadata(row: IngressDispatchOutboxRow) -> dict[str, Any]:
    return {
        "channel": row.channel,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "worker_id": row.worker_id,
        "next_attempt_at": _iso_or_none(row.next_attempt_at),
        "claimed_at": _iso_or_none(row.claimed_at),
        "last_error": row.last_error,
        **_sanitize_metadata(dict(row.metadata_json or {})),
    }


def _dedupe_and_sort_stages(
    stages: list[InboundMessageTimelineStageRecord],
) -> tuple[InboundMessageTimelineStageRecord, ...]:
    order = {
        "INGRESSED": 0,
        "ADMITTED": 1,
        "DISPATCH_DEFERRED": 2,
        "DISPATCHED": 3,
        "SESSION_CREATED": 4,
        "SESSION_LINKED": 4,
        "EXECUTION_STARTED": 5,
        "PROPOSAL_CREATED": 6,
        "GOVERNANCE_DECIDED": 7,
        "SEND_QUEUED": 8,
        "SENT": 9,
        "ESCALATED": 10,
        "DEAD_LETTERED": 11,
        "FAILED": 12,
        "UNKNOWN": 13,
    }
    seen: set[tuple[str, str, str]] = set()
    deduped: list[InboundMessageTimelineStageRecord] = []
    for stage in stages:
        key = (stage.stage, stage.source_table, stage.source_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(stage)
    deduped.sort(
        key=lambda item: (
            item.occurred_at,
            order.get(item.stage, 99),
            item.source_table,
            item.source_id,
        )
    )
    return tuple(deduped)


def _timeline_is_terminal(
    stages: tuple[InboundMessageTimelineStageRecord, ...],
    *,
    ingress: BoundaryIngressRow | None,
) -> bool:
    if any(stage.stage in {"SENT", "ESCALATED", "DEAD_LETTERED", "FAILED"} for stage in stages):
        return True
    if ingress is None:
        return False
    if ingress.replay_disposition != BoundaryReplayDisposition.NEW.value:
        return True
    if ingress.normalization_status != BoundaryNormalizationStatus.OK.value:
        return True
    if ingress.message_type in {"handshake", "quarantine"}:
        return True
    return False


def _timeline_stall_status(
    *,
    stages: tuple[InboundMessageTimelineStageRecord, ...],
    ingress: BoundaryIngressRow | None,
    dispatch_outbox: IngressDispatchOutboxRow | None,
    execution: ExecutionRow | None,
    proposal: ResolutionProposalRow | None,
    draft: ResolutionOutboundDraftRow | None,
    governance: GovernanceDecisionRow | None,
    outbound: OutboundSendOutboxRow | None,
    terminal: bool,
    latest_event_at: datetime | None,
    now: datetime,
    stall_threshold_seconds: int,
) -> tuple[bool, str | None]:
    if terminal or not stages or latest_event_at is None:
        return False, None
    if (now - latest_event_at).total_seconds() < stall_threshold_seconds:
        return False, None
    if ingress is not None and dispatch_outbox is None:
        return True, "ingressed_without_dispatch_outbox"
    if dispatch_outbox is not None and dispatch_outbox.status == "pending":
        return True, "dispatch_outbox_pending_stale"
    if dispatch_outbox is not None and dispatch_outbox.status == "claimed":
        return True, "dispatch_outbox_claimed_stale"
    if (
        draft is not None
        and proposal is not None
        and governance is not None
        and draft.status == "ready"
        and proposal.status == "send_eligible"
        and governance.decision == "allow"
        and outbound is None
    ):
        return True, "ready_allow_without_send_outbox"
    if (
        execution is not None
        and execution.state not in {"failed", "dead_lettered"}
        and proposal is None
        and draft is None
        and governance is None
    ):
        return True, "execution_without_proposal"
    if outbound is not None and outbound.status in {"pending", "claimed"}:
        return True, "outbound_send_not_terminal"
    return True, "latest_stage_stale"


def _proposal_send_eligible(
    proposal: ResolutionProposalRow | None,
    governance: GovernanceDecisionRow | None,
) -> bool:
    return (
        proposal is not None
        and governance is not None
        and proposal.status == "send_eligible"
        and proposal.governance_decision_id is not None
        and governance.decision == "allow"
    )


def _delivery_provider_message_id(
    email: EmailCustomerReplyDeliveryRow | None,
    whatsapp: WhatsAppCustomerReplyDeliveryRow | None,
) -> str | None:
    if email is not None and email.provider_message_id:
        return email.provider_message_id
    if whatsapp is not None and whatsapp.provider_message_id:
        return whatsapp.provider_message_id
    return None


def _delivery_sent_at(
    email: EmailCustomerReplyDeliveryRow | None,
    whatsapp: WhatsAppCustomerReplyDeliveryRow | None,
) -> datetime | None:
    if email is not None and email.sent_at is not None:
        return email.sent_at
    if whatsapp is not None and whatsapp.sent_at is not None:
        return whatsapp.sent_at
    return None


_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        metadata = cast(dict[Any, Any], value)
        result: dict[str, Any] = {}
        for key, inner in metadata.items():
            text_key = str(key)
            if _sensitive_key(text_key):
                continue
            sanitized = _sanitize_metadata(inner)
            if sanitized is not None:
                result[text_key] = sanitized
        return result
    if isinstance(value, list | tuple):
        sequence = cast(list[Any] | tuple[Any, ...], value)
        return [
            sanitized
            for item in sequence
            if (sanitized := _sanitize_metadata(item)) is not None
        ]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return None


def _sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _compact_metadata(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _uuid_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else _utc(value).isoformat()


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _dead_letter_row_to_record(row: ExecutionRow) -> DeadLetterExecutionRecord:
    return DeadLetterExecutionRecord(
        execution_id=str(row.execution_id),
        tenant_id=row.tenant_id,
        kind=row.kind,
        dispatch_id=row.dispatch_id,
        session_id=row.session_id,
        state=row.state,
        attempt_count=row.attempt_count,
        requested_at=row.requested_at,
        failed_at=row.failed_at,
        worker_id=row.worker_id,
        error=row.error,
        metadata=dict(row.metadata_json or {}),
    )


_STUCK_ALERT_NAMESPACE = uuid.UUID("4897a7e1-62ed-5ed7-a1c6-eaa1aee32c01")
_INBOUND_DLQ_NAMESPACE = uuid.UUID("4897a7e1-62ed-5ed7-a1c6-eaa1aee32c02")


def _stuck_alert_row_to_record(
    row: ExecutionRow,
    *,
    claimed_before_or_at: datetime,
) -> StuckExecutionAlertRecord:
    alert_id = uuid.uuid5(
        _STUCK_ALERT_NAMESPACE,
        f"{row.tenant_id}|{row.execution_id}|{claimed_before_or_at.isoformat()}",
    )
    return StuckExecutionAlertRecord(
        alert_id=str(alert_id),
        tenant_id=row.tenant_id,
        execution_id=str(row.execution_id),
        reason="execution_claim_exceeded_lease",
        claimed_at=row.claimed_at,
        worker_id=row.worker_id,
        metadata={"state": row.state},
    )


def _inbound_dead_letter_row_to_record(
    row: BoundaryIngressRow,
) -> InboundNormalizationDeadLetterRecord:
    tenant_id = row.tenant_id or ""
    dead_letter_id = uuid.uuid5(
        _INBOUND_DLQ_NAMESPACE,
        f"{tenant_id}|{row.ingress_id}|{row.normalization_status}",
    )
    return InboundNormalizationDeadLetterRecord(
        dead_letter_id=str(dead_letter_id),
        tenant_id=tenant_id,
        ingress_id=str(row.ingress_id),
        normalization_status=row.normalization_status,
        error=row.error,
        received_at=row.received_at,
        metadata=dict(row.metadata_json or {}),
    )


def _slo_record_to_row(
    record: OperationalSLODefinitionRecord,
) -> OperationalSLODefinitionRow:
    return OperationalSLODefinitionRow(
        slo_id=record.slo_id,
        tenant_id=record.tenant_id,
        metric_name=record.metric_name.value,
        threshold_operator=record.threshold_operator.value,
        threshold_value=record.threshold_value,
        window_minutes=record.window_minutes,
        severity=record.severity.value,
        enabled=record.enabled,
        created_at=record.created_at,
        updated_at=record.updated_at,
        metadata_json=dict(record.metadata),
    )


def _slo_row_to_record(
    row: OperationalSLODefinitionRow,
) -> OperationalSLODefinitionRecord:
    return OperationalSLODefinitionRecord(
        slo_id=OperationalSLODefinitionId(row.slo_id),
        tenant_id=row.tenant_id,
        metric_name=OperationalMetricName(row.metric_name),
        threshold_operator=AlertThresholdOperator(row.threshold_operator),
        threshold_value=row.threshold_value,
        window_minutes=row.window_minutes,
        severity=AlertSeverity(row.severity),
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_json or {}),
    )


def _trace_span_record_to_row(
    record: OperationalTraceSpanRecord,
) -> OperationalTraceSpanRow:
    return OperationalTraceSpanRow(
        span_id=record.span_id,
        tenant_id=record.tenant_id,
        trace_id=record.trace_id,
        parent_span_id=record.parent_span_id,
        span_name=record.span_name,
        substrate=record.substrate,
        operation=record.operation,
        started_at=record.started_at,
        ended_at=record.ended_at,
        latency_ms=record.latency_ms,
        status=record.status.value,
        error=record.error,
        attributes=dict(record.attributes),
        created_at=record.created_at or record.started_at,
    )


def _trace_span_row_to_record(
    row: OperationalTraceSpanRow,
) -> OperationalTraceSpanRecord:
    return OperationalTraceSpanRecord(
        span_id=OperationalTraceSpanId(row.span_id),
        tenant_id=row.tenant_id,
        trace_id=row.trace_id,
        parent_span_id=(
            OperationalTraceSpanId(row.parent_span_id)
            if row.parent_span_id is not None
            else None
        ),
        span_name=row.span_name,
        substrate=row.substrate,
        operation=row.operation,
        started_at=row.started_at,
        ended_at=row.ended_at,
        latency_ms=row.latency_ms,
        status=OperationalTraceStatus(row.status),
        error=row.error,
        attributes=dict(row.attributes or {}),
        created_at=row.created_at,
    )


def _assert_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise ValueError("record tenant_id does not match expected_tenant_id")


__all__ = ["PostgresOperationalObservabilityPersistence"]
