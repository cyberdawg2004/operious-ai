"""In-memory QA score repository."""

from __future__ import annotations

from app.qa.exceptions import QAPersistenceError
from app.qa.persistence.models import QAScorePage, QAScoreQuery
from app.qa.persistence.records import QAScoreRecord


class InMemoryQAPersistence:
    """Reference QA persistence implementation."""

    def __init__(self) -> None:
        self._scores: dict[str, QAScoreRecord] = {}
        self._inspection_index: dict[str, str] = {}

    async def record_score(
        self,
        record: QAScoreRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        if record.score_id in self._scores:
            raise QAPersistenceError(
                f"QA score {record.score_id!r} already recorded; "
                "records are write-once"
            )
        if record.inspection_id in self._inspection_index:
            raise QAPersistenceError(
                "QA score for supervisor inspection "
                f"{record.inspection_id!r} already recorded"
            )
        self._scores[record.score_id] = record
        self._inspection_index[record.inspection_id] = record.score_id

    async def get_score(
        self,
        score_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScoreRecord | None:
        record = self._scores.get(score_id)
        if record is None:
            return None
        if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
            return None
        return record

    async def get_score_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScoreRecord | None:
        score_id = self._inspection_index.get(inspection_id)
        if score_id is None:
            return None
        return await self.get_score(
            score_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_scores(
        self,
        query: QAScoreQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScorePage:
        records = [
            record
            for record in self._scores.values()
            if _matches(
                record,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        records.sort(key=lambda r: (r.scored_at, r.score_id))
        total = len(records)
        page = records[query.offset : query.offset + query.limit]
        return QAScorePage(items=tuple(page), total=total, offset=query.offset)


def _matches(
    record: QAScoreRecord,
    *,
    query: QAScoreQuery,
    expected_tenant_id: str | None,
) -> bool:
    if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
        return False
    if query.score_id is not None and record.score_id != query.score_id:
        return False
    if query.inspection_id is not None and record.inspection_id != query.inspection_id:
        return False
    if query.execution_id is not None and record.execution_id != query.execution_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if (
        query.supervisor_decision_kind is not None
        and record.supervisor_decision_kind != query.supervisor_decision_kind
    ):
        return False
    return True


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str | None,
) -> None:
    if expected_tenant_id is not None and tenant_id != expected_tenant_id:
        raise QAPersistenceError(
            "QA score tenant_id does not match expected_tenant_id"
        )


__all__ = ["InMemoryQAPersistence"]
