"""In-memory resolution proposal persistence."""

from __future__ import annotations

import asyncio

from app.resolution.exceptions import ResolutionPersistenceError
from app.resolution.persistence.models import (
    ResolutionOutboundDraftPage,
    ResolutionOutboundDraftQuery,
    ResolutionProposalPage,
    ResolutionProposalQuery,
)
from app.resolution.persistence.records import (
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)


class InMemoryResolutionProposalPersistence:
    """Reference tenant-scoped resolution proposal store."""

    def __init__(self) -> None:
        self._records: dict[str, ResolutionProposalRecord] = {}
        self._drafts: dict[str, ResolutionOutboundDraftRecord] = {}
        self._lock = asyncio.Lock()

    async def create_resolution_proposal(
        self,
        record: ResolutionProposalRecord,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            key = str(record.proposal_id)
            if key in self._records:
                raise ResolutionPersistenceError(
                    f"resolution proposal {key!r} already recorded"
                )
            self._records[key] = record
        return record

    async def get_resolution_proposal(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord | None:
        record = self._records.get(proposal_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_resolution_proposals(
        self,
        query: ResolutionProposalQuery,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalPage:
        rows = [
            record
            for record in self._records.values()
            if _matches(
                record,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        rows.sort(key=lambda item: (item.created_at, str(item.proposal_id)))
        total = len(rows)
        page = rows[query.offset : query.offset + query.limit]
        return ResolutionProposalPage(
            items=tuple(page),
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    async def create_resolution_outbound_draft(
        self,
        record: ResolutionOutboundDraftRecord,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            key = str(record.draft_id)
            if key in self._drafts:
                raise ResolutionPersistenceError(
                    f"resolution outbound draft {key!r} already recorded"
                )
            self._drafts[key] = record
        return record

    async def get_resolution_outbound_draft(
        self,
        draft_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRecord | None:
        record = self._drafts.get(draft_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_resolution_outbound_drafts(
        self,
        query: ResolutionOutboundDraftQuery,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftPage:
        rows = [
            draft
            for draft in self._drafts.values()
            if _matches_draft(
                draft,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        rows.sort(key=lambda item: (item.created_at, str(item.draft_id)))
        total = len(rows)
        page = rows[query.offset : query.offset + query.limit]
        return ResolutionOutboundDraftPage(
            items=tuple(page),
            total=total,
            limit=query.limit,
            offset=query.offset,
        )


def _matches(
    record: ResolutionProposalRecord,
    *,
    query: ResolutionProposalQuery,
    expected_tenant_id: str,
) -> bool:
    if record.tenant_id != expected_tenant_id:
        return False
    if query.proposal_id is not None and str(record.proposal_id) != query.proposal_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.session_id is not None and record.session_id != query.session_id:
        return False
    if query.execution_id is not None and record.execution_id != query.execution_id:
        return False
    if query.dispatch_id is not None and record.dispatch_id != query.dispatch_id:
        return False
    if query.status is not None and record.status.value != query.status:
        return False
    return True


def _matches_draft(
    record: ResolutionOutboundDraftRecord,
    *,
    query: ResolutionOutboundDraftQuery,
    expected_tenant_id: str,
) -> bool:
    if record.tenant_id != expected_tenant_id:
        return False
    if query.draft_id is not None and str(record.draft_id) != query.draft_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.proposal_id is not None and str(record.proposal_id) != query.proposal_id:
        return False
    if query.session_id is not None and record.session_id != query.session_id:
        return False
    if query.execution_id is not None and record.execution_id != query.execution_id:
        return False
    if query.dispatch_id is not None and record.dispatch_id != query.dispatch_id:
        return False
    if query.status is not None and record.status.value != query.status:
        return False
    return True


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str,
) -> None:
    if tenant_id != expected_tenant_id:
        raise ResolutionPersistenceError(
            "resolution proposal tenant_id does not match expected_tenant_id"
        )


__all__ = ["InMemoryResolutionProposalPersistence"]
