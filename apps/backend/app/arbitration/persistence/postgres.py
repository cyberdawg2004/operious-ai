"""Postgres implementation of :class:`ArbitrationPersistenceProtocol`.

Behavioural parity with :class:`InMemoryArbitrationPersistence` —
write-once apex records, tenant-scoped point + list reads,
canonical ``(runtime_instance_id, sequence)`` ordering.

Nested ``findings`` / ``conflicts`` / ``deadlock_witnesses`` are
serialised as JSONB arrays on the same row. Each nested element
round-trips through dataclass field unpacking — the substrate's
contract is "one apex record = one row", not "one apex + N child
tables".
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.arbitration.db.models import ArbitrationEvaluationRow
from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationDeadlockKind,
    ArbitrationOutcome,
)
from app.arbitration.exceptions import ArbitrationPersistenceError
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationChainId,
    ArbitrationConflictId,
    ArbitrationEvaluationId,
)
from app.arbitration.persistence.models import (
    ArbitrationQuery,
    RecordPage,
)
from app.arbitration.persistence.records import (
    ArbitrationConflictRecord,
    ArbitrationDeadlockRecord,
    ArbitrationFindingRecord,
    ArbitrationRecord,
)
from app.repositories.base import BaseRepository


class PostgresArbitrationPersistence(BaseRepository):
    """Postgres-backed arbitration persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def save(self, record: ArbitrationRecord) -> None:
        row = _record_to_row(record)
        try:
            # SAVEPOINT isolation — see governance / coordination
            # repos for the doctrine rationale.
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise ArbitrationPersistenceError(
                f"duplicate arbitration record: evaluation_id="
                f"{record.evaluation_id}"
            ) from exc

    # ─── Reads ───────────────────────────────────────────────────────

    async def get(
        self,
        evaluation_id: ArbitrationEvaluationId,
        *,
        expected_tenant_id: str | None = None,
    ) -> ArbitrationRecord | None:
        stmt = select(ArbitrationEvaluationRow).where(
            ArbitrationEvaluationRow.evaluation_id == evaluation_id
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.tenant_id == expected_tenant_id
            )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list_records(
        self,
        query: ArbitrationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> RecordPage:
        stmt = select(ArbitrationEvaluationRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.tenant_id == expected_tenant_id
            )
        if query.case_id is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.case_id == query.case_id
            )
        if query.evaluation_id is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.evaluation_id
                == query.evaluation_id
            )
        if query.outcome is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.outcome == query.outcome.value
            )
        if query.correlation_id is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.correlation_id
                == query.correlation_id
            )
        if query.request_id is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.request_id == query.request_id
            )
        if query.tenant_id is not None:
            stmt = stmt.where(
                ArbitrationEvaluationRow.tenant_id == query.tenant_id
            )
        stmt = stmt.order_by(
            ArbitrationEvaluationRow.runtime_instance_id,
            ArbitrationEvaluationRow.sequence,
        )
        all_rows = list(
            (await self.session.execute(stmt)).scalars().all()
        )
        total = len(all_rows)
        sliced = all_rows[query.offset :]
        if query.limit is not None:
            sliced = sliced[: query.limit]
        return RecordPage(
            records=tuple(_row_to_record(r) for r in sliced),
            total=total,
        )


# ─── Record ↔ Row converters ────────────────────────────────────────────


def _record_to_row(record: ArbitrationRecord) -> ArbitrationEvaluationRow:
    return ArbitrationEvaluationRow(
        evaluation_id=record.evaluation_id,
        chain_id=record.chain_id,
        case_id=record.case_id,
        runtime_instance_id=record.runtime_instance_id,
        sequence=record.sequence,
        outcome=record.outcome.value,
        prevailing_authority_level=(
            record.prevailing_authority_level.value
            if record.prevailing_authority_level is not None
            else None
        ),
        prevailing_authority_source_substrate=(
            record.prevailing_authority_source_substrate
        ),
        prevailing_authority_source_id=record.prevailing_authority_source_id,
        prevailing_authority_verdict=record.prevailing_authority_verdict,
        reason=record.reason,
        evaluator_names=list(record.evaluator_names),
        findings=[_finding_to_dict(f) for f in record.findings],
        conflicts=[_conflict_to_dict(c) for c in record.conflicts],
        deadlock_witnesses=[
            _deadlock_to_dict(d) for d in record.deadlock_witnesses
        ],
        signal_count=record.signal_count,
        recommendation_count=record.recommendation_count,
        iteration_count=record.iteration_count,
        max_iterations=record.max_iterations,
        correlation_id=record.correlation_id,
        request_id=record.request_id,
        tenant_id=record.tenant_id,
        started_at=record.started_at,
        ended_at=record.ended_at,
        latency_ms=record.latency_ms,
        error=record.error,
        governance_decision_id=record.governance_decision_id,
        governance_chain_id=record.governance_chain_id,
        metadata_json=dict(record.metadata),
    )


def _row_to_record(row: ArbitrationEvaluationRow) -> ArbitrationRecord:
    return ArbitrationRecord(
        evaluation_id=ArbitrationEvaluationId(row.evaluation_id),
        chain_id=ArbitrationChainId(row.chain_id),
        case_id=ArbitrationCaseId(row.case_id),
        runtime_instance_id=row.runtime_instance_id,
        sequence=row.sequence,
        outcome=ArbitrationOutcome(row.outcome),
        prevailing_authority_level=(
            ArbitrationAuthorityLevel(row.prevailing_authority_level)
            if row.prevailing_authority_level is not None
            else None
        ),
        prevailing_authority_source_substrate=(
            row.prevailing_authority_source_substrate
        ),
        prevailing_authority_source_id=row.prevailing_authority_source_id,
        prevailing_authority_verdict=row.prevailing_authority_verdict,
        reason=row.reason,
        evaluator_names=tuple(_as_list_of_str(row.evaluator_names)),
        findings=tuple(
            _dict_to_finding(f)
            for f in _as_list_of_dict(row.findings)
        ),
        conflicts=tuple(
            _dict_to_conflict(c)
            for c in _as_list_of_dict(row.conflicts)
        ),
        deadlock_witnesses=tuple(
            _dict_to_deadlock(d)
            for d in _as_list_of_dict(row.deadlock_witnesses)
        ),
        signal_count=row.signal_count,
        recommendation_count=row.recommendation_count,
        iteration_count=row.iteration_count,
        max_iterations=row.max_iterations,
        correlation_id=row.correlation_id,
        request_id=row.request_id,
        tenant_id=row.tenant_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        latency_ms=row.latency_ms,
        error=row.error,
        governance_decision_id=row.governance_decision_id,
        governance_chain_id=row.governance_chain_id,
        metadata=dict(_as_dict(row.metadata_json)),
    )


# ─── Nested record ↔ JSON dict converters ───────────────────────────────


def _finding_to_dict(f: ArbitrationFindingRecord) -> dict[str, Any]:
    return {
        "finding_id": str(f.finding_id),
        "evaluator_name": f.evaluator_name,
        "outcome_hint": f.outcome_hint.value,
        "code": f.code,
        "message": f.message,
        "detected_at": (
            f.detected_at.isoformat() if f.detected_at is not None else None
        ),
        "related_conflict_id": (
            str(f.related_conflict_id)
            if f.related_conflict_id is not None
            else None
        ),
        "related_deadlock_witness_id": (
            str(f.related_deadlock_witness_id)
            if f.related_deadlock_witness_id is not None
            else None
        ),
        "authority": (
            f.authority.value if f.authority is not None else None
        ),
        "metadata": dict(f.metadata),
    }


def _dict_to_finding(d: dict[str, Any]) -> ArbitrationFindingRecord:
    from datetime import datetime

    detected_raw = d.get("detected_at")
    return ArbitrationFindingRecord(
        finding_id=uuid.UUID(str(d["finding_id"])),
        evaluator_name=str(d["evaluator_name"]),
        outcome_hint=ArbitrationOutcome(str(d["outcome_hint"])),
        code=str(d["code"]),
        message=str(d["message"]),
        detected_at=(
            datetime.fromisoformat(str(detected_raw))
            if detected_raw is not None
            else None
        ),
        related_conflict_id=(
            ArbitrationConflictId(uuid.UUID(str(d["related_conflict_id"])))
            if d.get("related_conflict_id") is not None
            else None
        ),
        related_deadlock_witness_id=(
            uuid.UUID(str(d["related_deadlock_witness_id"]))
            if d.get("related_deadlock_witness_id") is not None
            else None
        ),
        authority=(
            ArbitrationAuthorityLevel(str(d["authority"]))
            if d.get("authority") is not None
            else None
        ),
        metadata=dict(d.get("metadata") or {}),
    )


def _conflict_to_dict(c: ArbitrationConflictRecord) -> dict[str, Any]:
    return {
        "conflict_id": str(c.conflict_id),
        "kind": c.kind.value,
        "participants": list(c.participants),
        "participant_authorities": [
            a.value for a in c.participant_authorities
        ],
        "summary": c.summary,
        "metadata": dict(c.metadata),
    }


def _dict_to_conflict(d: dict[str, Any]) -> ArbitrationConflictRecord:
    return ArbitrationConflictRecord(
        conflict_id=ArbitrationConflictId(
            uuid.UUID(str(d["conflict_id"]))
        ),
        kind=ArbitrationConflictKind(str(d["kind"])),
        participants=tuple(str(p) for p in d.get("participants") or ()),
        participant_authorities=tuple(
            ArbitrationAuthorityLevel(str(a))
            for a in d.get("participant_authorities") or ()
        ),
        summary=str(d.get("summary", "")),
        metadata=dict(d.get("metadata") or {}),
    )


def _deadlock_to_dict(d: ArbitrationDeadlockRecord) -> dict[str, Any]:
    return {
        "witness_id": str(d.witness_id),
        "kind": d.kind.value,
        "contributing_ids": list(d.contributing_ids),
        "summary": d.summary,
        "iteration_count": d.iteration_count,
        "metadata": dict(d.metadata),
    }


def _dict_to_deadlock(d: dict[str, Any]) -> ArbitrationDeadlockRecord:
    return ArbitrationDeadlockRecord(
        witness_id=uuid.UUID(str(d["witness_id"])),
        kind=ArbitrationDeadlockKind(str(d["kind"])),
        contributing_ids=tuple(
            str(x) for x in d.get("contributing_ids") or ()
        ),
        summary=str(d.get("summary", "")),
        iteration_count=int(d.get("iteration_count", 0)),
        metadata=dict(d.get("metadata") or {}),
    )


# ─── JSONB coercion helpers ─────────────────────────────────────────────


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return []


def _as_list_of_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(item, dict):
            out.append({str(k): v for k, v in item.items()})  # pyright: ignore[reportUnknownVariableType]
    return out


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return {}


__all__ = ["PostgresArbitrationPersistence"]
