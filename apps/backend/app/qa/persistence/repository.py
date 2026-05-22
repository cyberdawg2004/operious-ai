"""Storage-agnostic QA persistence contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.qa.persistence.models import QAScorePage, QAScoreQuery
from app.qa.persistence.records import QAScoreRecord


@runtime_checkable
class QAPersistenceProtocol(Protocol):
    """Durable QA score persistence boundary."""

    async def record_score(
        self,
        record: QAScoreRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None: ...

    async def get_score(
        self,
        score_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScoreRecord | None: ...

    async def get_score_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScoreRecord | None: ...

    async def list_scores(
        self,
        query: QAScoreQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScorePage: ...


__all__ = ["QAPersistenceProtocol"]
