"""Semantic quarantine service and persistence boundary."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from sqlalchemy import Select, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import (
    EventCausality,
    EventChronology,
    OperationalEvent,
    OperationalSubstrate,
    derive_event_id,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.identity import derive_decision_id
from app.governance.persistence import (
    BaseGovernanceRepository,
    GovernanceDecisionRecord,
    PolicyEvaluationResultRecord,
    PolicyViolationRecord,
    PostgresGovernanceRepository,
)
from app.queues import (
    QUEUE_INGRESS_EMAIL,
    QUEUE_INGRESS_VOICE,
    QUEUE_INGRESS_WHATSAPP,
    QUEUE_SEMANTIC_QUARANTINE,
)
from app.repositories.base import BaseRepository
from app.semantic.db.models import SemanticQuarantineRecordRow

SEMANTIC_QUARANTINE_PENDING = "pending"
SEMANTIC_QUARANTINE_FALSE_POSITIVE = "false_positive"
SEMANTIC_QUARANTINE_FRAUD_CONFIRMED = "fraud_confirmed"

_FRAUD_POLICY_CHAIN_ID = "semantic_quarantine.fraud_determination.v1"
_FRAUD_POLICY_NAME = "semantic_quarantine_operator_review"
_FRAUD_RULE_ID = "fraud_confirmed"
_FRAUD_GOVERNANCE_VERSION = "phase-2-2.semantic-quarantine.v1"
_FRAUD_REASON = "fraud_determination"
_ORIGINAL_QUEUE_BY_CHANNEL = {
    "email": QUEUE_INGRESS_EMAIL,
    "voice": QUEUE_INGRESS_VOICE,
    "whatsapp": QUEUE_INGRESS_WHATSAPP,
}

logger = logging.getLogger(__name__)


class SemanticQuarantineNotFoundError(LookupError):
    """Raised when a quarantine record is not visible to the tenant."""


class SemanticQuarantineAlreadyReviewedError(ValueError):
    """Raised when a non-pending quarantine record is released again."""


class SemanticQuarantineReingestUnavailableError(RuntimeError):
    """Raised when FALSE_POSITIVE release has no re-ingest callback."""


class SemanticQuarantinePublisher(Protocol):
    """Publish one frozen quarantine notification."""

    def publish(
        self,
        *,
        quarantine_id: str,
        tenant_id: str,
        payload: Mapping[str, Any],
    ) -> None: ...


class TicketReingestCallback(Protocol):
    def __call__(
        self,
        *,
        external_id: str,
        channel: str,
        raw_content: str,
        language_code: str,
        expected_tenant_id: str,
        semantic_quarantine_enabled: bool,
    ) -> Awaitable[object]: ...


class OperationalEventAppenderProtocol(Protocol):
    async def append_event(
        self,
        event: OperationalEvent,
        *,
        expected_tenant_id: str | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class SemanticQuarantineRecord:
    quarantine_id: str
    tenant_id: str
    channel: str
    original_queue: str
    external_id: str | None
    ticket_payload_json: dict[str, Any]
    fingerprint_json: list[int]
    cluster_size: int
    similarity_threshold: float
    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    resolution_note: str | None
    created_at: datetime
    metadata: dict[str, Any]


class SemanticQuarantineRepository(BaseRepository):
    """Tenant-scoped repository for mutable semantic quarantine records."""

    async def create(
        self,
        *,
        tenant_id: str,
        channel: str,
        original_queue: str,
        external_id: str | None,
        ticket_payload_json: Mapping[str, Any],
        fingerprint_json: Sequence[int],
        cluster_size: int,
        similarity_threshold: float,
        metadata: Mapping[str, Any] | None = None,
    ) -> SemanticQuarantineRecord:
        quarantine_id = uuid.uuid4()  # APPROVED_EXCEPTION: operator-reviewed quarantine record id
        values = {
            "quarantine_id": quarantine_id,
            "tenant_id": tenant_id,
            "channel": channel,
            "original_queue": original_queue,
            "external_id": external_id,
            "ticket_payload_json": dict(ticket_payload_json),
            "fingerprint_json": [int(value) for value in fingerprint_json],
            "cluster_size": cluster_size,
            "similarity_threshold": similarity_threshold,
            "metadata_json": dict(metadata or {}),
        }
        statement = (
            insert(SemanticQuarantineRecordRow)
            .values(**values)
            .returning(SemanticQuarantineRecordRow)
        )
        row = (await self.session.execute(statement)).scalar_one()
        return _record_from_row(row)

    async def get(
        self,
        *,
        quarantine_id: str,
        expected_tenant_id: str,
    ) -> SemanticQuarantineRecord | None:
        statement = select(SemanticQuarantineRecordRow).where(
            SemanticQuarantineRecordRow.quarantine_id == uuid.UUID(quarantine_id),
            SemanticQuarantineRecordRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(statement)).scalar_one_or_none()
        return None if row is None else _record_from_row(row)

    async def list_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[SemanticQuarantineRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        bounded_limit = max(1, min(limit, 500))
        statement: Select[tuple[SemanticQuarantineRecordRow]] = select(
            SemanticQuarantineRecordRow
        ).where(SemanticQuarantineRecordRow.tenant_id == tenant_id)
        if status is not None:
            statement = statement.where(
                SemanticQuarantineRecordRow.status == status
            )
        rows = (
            await self.session.scalars(
                statement.order_by(
                    SemanticQuarantineRecordRow.created_at.desc()
                ).limit(bounded_limit)
            )
        ).all()
        return [_record_from_row(row) for row in rows]

    async def mark_reviewed(
        self,
        *,
        quarantine_id: str,
        status: str,
        reviewed_by: str,
        reviewed_at: datetime,
        resolution_note: str | None,
        expected_tenant_id: str,
    ) -> SemanticQuarantineRecord:
        statement = (
            update(SemanticQuarantineRecordRow)
            .where(
                SemanticQuarantineRecordRow.quarantine_id
                == uuid.UUID(quarantine_id),
                SemanticQuarantineRecordRow.tenant_id == expected_tenant_id,
                SemanticQuarantineRecordRow.status
                == SEMANTIC_QUARANTINE_PENDING,
            )
            .values(
                status=status,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                resolution_note=resolution_note,
            )
            .returning(SemanticQuarantineRecordRow)
        )
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is not None:
            return _record_from_row(row)
        existing = await self.get(
            quarantine_id=quarantine_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is None:
            raise SemanticQuarantineNotFoundError("quarantine record not found")
        raise SemanticQuarantineAlreadyReviewedError(
            "quarantine record has already been reviewed"
        )


class QuarantineService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: SemanticQuarantineRepository | None = None,
        governance_repository: BaseGovernanceRepository | None = None,
        publisher: SemanticQuarantinePublisher | None = None,
        ticket_reingest: TicketReingestCallback | None = None,
        event_runtime: OperationalEventAppenderProtocol | None = None,
    ) -> None:
        self._session = session
        self._repository = repository or SemanticQuarantineRepository(session)
        self._governance_repository = (
            governance_repository or PostgresGovernanceRepository(session)
        )
        self._publisher = publisher or _UnavailableSemanticQuarantinePublisher()
        self._ticket_reingest = ticket_reingest
        self._event_runtime = event_runtime

    async def quarantine_ticket(
        self,
        *,
        tenant_id: str,
        channel: str,
        external_id: str | None,
        ticket_payload: dict[str, Any],
        fingerprint: list[int],
        cluster_size: int,
        similarity_threshold: float,
        expected_tenant_id: str,
    ) -> str:
        _assert_tenant(tenant_id, expected_tenant_id)
        record = await self._repository.create(
            tenant_id=tenant_id,
            channel=channel,
            original_queue=_original_queue_for_channel(channel),
            external_id=external_id,
            ticket_payload_json=ticket_payload,
            fingerprint_json=fingerprint,
            cluster_size=cluster_size,
            similarity_threshold=similarity_threshold,
            metadata={
                "_schema_version": "1",
                "semantic_quarantine_queue": QUEUE_SEMANTIC_QUARANTINE,
            },
        )
        await self._append_quarantine_operational_event(record)
        try:
            self._publisher.publish(
                quarantine_id=record.quarantine_id,
                tenant_id=tenant_id,
                payload={
                    "quarantine_id": record.quarantine_id,
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "external_id": external_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "semantic_quarantine_publish_failed",
                extra={
                    "quarantine_id": record.quarantine_id,
                    "tenant_id": tenant_id,
                    "error": str(exc),
                },
            )
        return record.quarantine_id

    async def _append_quarantine_operational_event(
        self,
        record: SemanticQuarantineRecord,
    ) -> None:
        if self._event_runtime is None:
            return
        try:
            async with self._session.begin_nested():
                await self._event_runtime.append_event(
                    _semantic_quarantine_operational_event(record),
                    expected_tenant_id=record.tenant_id,
                )
        except Exception as exc:  # noqa: BLE001 - event emission is fail-open.
            logger.warning(
                "semantic_quarantine_event_failed",
                extra={
                    "quarantine_id": record.quarantine_id,
                    "tenant_id": record.tenant_id,
                    "error": str(exc),
                },
            )

    async def release(
        self,
        *,
        quarantine_id: str,
        verdict: str,
        reviewed_by: str,
        note: str | None,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> SemanticQuarantineRecord:
        _assert_tenant(tenant_id, expected_tenant_id)
        if verdict not in {
            SEMANTIC_QUARANTINE_FALSE_POSITIVE,
            SEMANTIC_QUARANTINE_FRAUD_CONFIRMED,
        }:
            raise ValueError("unsupported semantic quarantine verdict")
        existing = await self._repository.get(
            quarantine_id=quarantine_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is None:
            raise SemanticQuarantineNotFoundError("quarantine record not found")
        if existing.status != SEMANTIC_QUARANTINE_PENDING:
            raise SemanticQuarantineAlreadyReviewedError(
                "quarantine record has already been reviewed"
            )

        reviewed_at = datetime.now(timezone.utc)
        updated = await self._repository.mark_reviewed(
            quarantine_id=quarantine_id,
            status=verdict,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            resolution_note=note,
            expected_tenant_id=expected_tenant_id,
        )
        if verdict == SEMANTIC_QUARANTINE_FALSE_POSITIVE:
            await self._release_false_positive(updated)
        else:
            await self._record_fraud_decision(
                record=updated,
                reviewed_by=reviewed_by,
                note=note,
                decided_at=reviewed_at,
            )
        await self._session.commit()
        return updated

    async def list_pending(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int = 50,
    ) -> list[SemanticQuarantineRecord]:
        return await self._repository.list_for_tenant(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            status=SEMANTIC_QUARANTINE_PENDING,
            limit=limit,
        )

    async def list_records(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[SemanticQuarantineRecord]:
        return await self._repository.list_for_tenant(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            status=status,
            limit=limit,
        )

    async def _release_false_positive(
        self,
        record: SemanticQuarantineRecord,
    ) -> None:
        if self._ticket_reingest is None:
            raise SemanticQuarantineReingestUnavailableError(
                "ticket re-ingest callback is not configured"
            )
        payload = record.ticket_payload_json
        await self._ticket_reingest(
            external_id=_payload_string(payload, "external_id")
            or record.external_id
            or record.quarantine_id,
            channel=_payload_string(payload, "channel") or record.channel,
            raw_content=_payload_string(payload, "content") or "",
            language_code=_payload_string(payload, "language_code") or "en",
            expected_tenant_id=record.tenant_id,
            semantic_quarantine_enabled=False,
        )

    async def _record_fraud_decision(
        self,
        *,
        record: SemanticQuarantineRecord,
        reviewed_by: str,
        note: str | None,
        decided_at: datetime,
    ) -> None:
        metadata = {
            "_schema_version": "1",
            "quarantine_id": record.quarantine_id,
            "channel": record.channel,
            "external_id": record.external_id,
            "reviewed_by": reviewed_by,
            "resolution_note": note,
            "cluster_size": record.cluster_size,
            "similarity_threshold": record.similarity_threshold,
        }
        decided_at_iso = decided_at.isoformat()
        decision_record = GovernanceDecisionRecord(
            decision_id=str(
                derive_decision_id(
                    seed=(
                        "semantic_quarantine:"
                        f"{record.tenant_id}:{record.quarantine_id}:fraud"
                    )
                )
            ),
            decision=Decision.DENY.value,
            stage=EnforcementStage.PRE_REQUEST.value,
            policy_chain_id=_FRAUD_POLICY_CHAIN_ID,
            reason=_FRAUD_REASON,
            decided_at=decided_at_iso,
            correlation_id=record.external_id,
            request_id=record.external_id,
            tenant_id=record.tenant_id,
            subject_kind=_FRAUD_REASON,
            governance_version=_FRAUD_GOVERNANCE_VERSION,
            violations=(
                PolicyViolationRecord(
                    policy_name=_FRAUD_POLICY_NAME,
                    rule_id=_FRAUD_RULE_ID,
                    decision=Decision.DENY.value,
                    severity=ViolationSeverity.CRITICAL.value,
                    detail=_FRAUD_REASON,
                    metadata=metadata,
                ),
            ),
            evaluated_rules=(
                PolicyEvaluationResultRecord(
                    policy_name=_FRAUD_POLICY_NAME,
                    rule_id=_FRAUD_RULE_ID,
                    decision=Decision.DENY.value,
                    severity=ViolationSeverity.CRITICAL.value,
                    reason=_FRAUD_REASON,
                    evaluated_at=decided_at_iso,
                    metadata=metadata,
                    policy_version=_FRAUD_GOVERNANCE_VERSION,
                ),
            ),
            metadata=metadata,
        )
        await self._governance_repository.record_decision(decision_record)


def _record_from_row(row: SemanticQuarantineRecordRow) -> SemanticQuarantineRecord:
    return SemanticQuarantineRecord(
        quarantine_id=str(row.quarantine_id),
        tenant_id=row.tenant_id,
        channel=row.channel,
        original_queue=row.original_queue,
        external_id=row.external_id,
        ticket_payload_json=dict(row.ticket_payload_json or {}),
        fingerprint_json=[
            int(value)
            for value in cast(Sequence[object], row.fingerprint_json or [])
            if isinstance(value, int)
        ],
        cluster_size=row.cluster_size,
        similarity_threshold=row.similarity_threshold,
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        resolution_note=row.resolution_note,
        created_at=row.created_at,
        metadata=dict(row.metadata_json or {}),
    )


def _semantic_quarantine_operational_event(
    record: SemanticQuarantineRecord,
) -> OperationalEvent:
    runtime_instance_id = uuid.UUID(record.quarantine_id)
    sequence = 0
    event_id = derive_event_id(
        operational_act=OperationalAct.SEMANTIC_QUARANTINE_CREATED.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        tenant_id=record.tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.SEMANTIC_QUARANTINE_CREATED,
        substrate=OperationalSubstrate.BOUNDARY,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            occurred_at=record.created_at,
        ),
        tenant_id=record.tenant_id,
        metadata={
            "_schema_version": "1",
            "quarantine_id": record.quarantine_id,
            "tenant_id": record.tenant_id,
            "channel": record.channel,
            "cluster_size": record.cluster_size,
        },
    )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("tenant_id does not match expected_tenant_id")


def _original_queue_for_channel(channel: str) -> str:
    return _ORIGINAL_QUEUE_BY_CHANNEL.get(channel, QUEUE_INGRESS_EMAIL)


def _payload_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


class _UnavailableSemanticQuarantinePublisher:
    def publish(
        self,
        *,
        quarantine_id: str,
        tenant_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        raise RuntimeError("semantic quarantine publisher is not configured")


__all__ = [
    "QuarantineService",
    "SEMANTIC_QUARANTINE_FALSE_POSITIVE",
    "SEMANTIC_QUARANTINE_FRAUD_CONFIRMED",
    "SEMANTIC_QUARANTINE_PENDING",
    "SemanticQuarantineAlreadyReviewedError",
    "SemanticQuarantineNotFoundError",
    "SemanticQuarantinePublisher",
    "SemanticQuarantineRecord",
    "SemanticQuarantineRepository",
    "SemanticQuarantineReingestUnavailableError",
    "TicketReingestCallback",
]
