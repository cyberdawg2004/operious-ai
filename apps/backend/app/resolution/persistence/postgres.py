"""Postgres implementation of resolution proposal persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, TypeGuard
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.data_protection.crypto import DataProtectionService
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page
from app.resolution.db.models import (
    ResolutionOutboundDraftRow,
    ResolutionProposalRow,
)
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.exceptions import ResolutionPersistenceError
from app.resolution.identity import (
    as_resolution_outbound_draft_id,
    as_resolution_proposal_id,
)
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


class PostgresResolutionProposalPersistence(BaseRepository):
    """Postgres-backed resolution proposal persistence."""

    def __init__(
        self,
        session: Any,
        *,
        data_protection: DataProtectionService | None = None,
    ) -> None:
        super().__init__(session)
        self._data_protection = data_protection

    async def create_resolution_proposal(
        self,
        record: ResolutionProposalRecord,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        protected_record = await self._protect_proposal(record)
        row = _record_to_row(protected_record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise ResolutionPersistenceError(
                f"resolution proposal {record.proposal_id!s} already recorded"
            ) from exc
        return record

    async def get_resolution_proposal(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord | None:
        row = await self._proposal_row(
            proposal_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else await self._row_to_record(row)

    async def list_resolution_proposals(
        self,
        query: ResolutionProposalQuery,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalPage:
        stmt = select(ResolutionProposalRow).where(
            ResolutionProposalRow.tenant_id == expected_tenant_id
        )
        stmt = _apply_filters(stmt, query=query)
        stmt = stmt.order_by(
            ResolutionProposalRow.created_at,
            ResolutionProposalRow.proposal_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return ResolutionProposalPage(
            items=tuple([await self._row_to_record(row) for row in page.items]),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def create_resolution_outbound_draft(
        self,
        record: ResolutionOutboundDraftRecord,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        protected_record = await self._protect_draft(record)
        row = _draft_record_to_row(protected_record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise ResolutionPersistenceError(
                f"resolution outbound draft {record.draft_id!s} already recorded"
            ) from exc
        return record

    async def get_resolution_outbound_draft(
        self,
        draft_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRecord | None:
        row = await self._draft_row(
            draft_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else await self._draft_row_to_record(row)

    async def list_resolution_outbound_drafts(
        self,
        query: ResolutionOutboundDraftQuery,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftPage:
        stmt = select(ResolutionOutboundDraftRow).where(
            ResolutionOutboundDraftRow.tenant_id == expected_tenant_id
        )
        stmt = _apply_draft_filters(stmt, query=query)
        stmt = stmt.order_by(
            ResolutionOutboundDraftRow.created_at,
            ResolutionOutboundDraftRow.draft_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return ResolutionOutboundDraftPage(
            items=tuple(
                [await self._draft_row_to_record(row) for row in page.items]
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def _protect_proposal(
        self,
        record: ResolutionProposalRecord,
    ) -> ResolutionProposalRecord:
        if self._data_protection is None:
            return record
        subject_id = (
            record.session_id or record.execution_id or str(record.proposal_id)
        )
        proposed_customer_reply = await self._data_protection.encrypt_text(
            record.proposed_customer_reply,
            tenant_id=record.tenant_id,
            subject_id=subject_id,
            field="resolution_proposals.proposed_customer_reply",
        )
        evidence_items: list[dict[str, Any]] = []
        for item in record.evidence:
            evidence_items.append(
                await self._data_protection.encrypt_json_values(
                    dict(item),
                    tenant_id=record.tenant_id,
                    subject_id=subject_id,
                    field="resolution_proposals.evidence",
                )
            )
        return replace(
            record,
            proposed_customer_reply=proposed_customer_reply,
            evidence=tuple(evidence_items),
        )

    async def _protect_draft(
        self,
        record: ResolutionOutboundDraftRecord,
    ) -> ResolutionOutboundDraftRecord:
        if self._data_protection is None:
            return record
        draft_body = await self._data_protection.encrypt_text(
            record.draft_body,
            tenant_id=record.tenant_id,
            subject_id=record.session_id or record.execution_id,
            field="resolution_outbound_drafts.draft_body",
        )
        metadata = await self._data_protection.encrypt_json_values(
            dict(record.metadata),
            tenant_id=record.tenant_id,
            subject_id=record.session_id or record.execution_id,
            field="resolution_outbound_drafts.metadata_json",
        )
        return replace(record, draft_body=draft_body, metadata=metadata)

    async def _row_to_record(
        self,
        row: ResolutionProposalRow,
    ) -> ResolutionProposalRecord:
        record = _row_to_record(row)
        if self._data_protection is None:
            return record
        proposed_customer_reply = await self._data_protection.decrypt_text(
            record.proposed_customer_reply
        )
        evidence_items: list[dict[str, Any]] = []
        for item in record.evidence:
            evidence_items.append(
                await self._data_protection.decrypt_json_values(dict(item))
            )
        return replace(
            record,
            proposed_customer_reply=proposed_customer_reply,
            evidence=tuple(evidence_items),
        )

    async def _draft_row_to_record(
        self,
        row: ResolutionOutboundDraftRow,
    ) -> ResolutionOutboundDraftRecord:
        record = _draft_row_to_record(row)
        if self._data_protection is None:
            return record
        draft_body = await self._data_protection.decrypt_text(record.draft_body)
        metadata = await self._data_protection.decrypt_json_values(dict(record.metadata))
        return replace(record, draft_body=draft_body, metadata=metadata)

    async def _proposal_row(
        self,
        proposal_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRow | None:
        stmt = select(ResolutionProposalRow).where(
            ResolutionProposalRow.proposal_id == UUID(proposal_id),
            ResolutionProposalRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _draft_row(
        self,
        draft_id: str,
        *,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRow | None:
        stmt = select(ResolutionOutboundDraftRow).where(
            ResolutionOutboundDraftRow.draft_id == UUID(draft_id),
            ResolutionOutboundDraftRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _apply_filters(
    stmt: Select[tuple[ResolutionProposalRow]],
    *,
    query: ResolutionProposalQuery,
) -> Select[tuple[ResolutionProposalRow]]:
    if query.proposal_id is not None:
        stmt = stmt.where(
            ResolutionProposalRow.proposal_id == UUID(query.proposal_id)
        )
    if query.tenant_id is not None:
        stmt = stmt.where(ResolutionProposalRow.tenant_id == query.tenant_id)
    if query.session_id is not None:
        stmt = stmt.where(
            ResolutionProposalRow.session_id == UUID(query.session_id)
        )
    if query.execution_id is not None:
        stmt = stmt.where(
            ResolutionProposalRow.execution_id == UUID(query.execution_id)
        )
    if query.dispatch_id is not None:
        stmt = stmt.where(
            ResolutionProposalRow.dispatch_id == UUID(query.dispatch_id)
        )
    if query.status is not None:
        stmt = stmt.where(ResolutionProposalRow.status == query.status)
    return stmt


def _apply_draft_filters(
    stmt: Select[tuple[ResolutionOutboundDraftRow]],
    *,
    query: ResolutionOutboundDraftQuery,
) -> Select[tuple[ResolutionOutboundDraftRow]]:
    if query.draft_id is not None:
        stmt = stmt.where(
            ResolutionOutboundDraftRow.draft_id == UUID(query.draft_id)
        )
    if query.tenant_id is not None:
        stmt = stmt.where(ResolutionOutboundDraftRow.tenant_id == query.tenant_id)
    if query.proposal_id is not None:
        stmt = stmt.where(
            ResolutionOutboundDraftRow.proposal_id == UUID(query.proposal_id)
        )
    if query.session_id is not None:
        stmt = stmt.where(ResolutionOutboundDraftRow.session_id == query.session_id)
    if query.execution_id is not None:
        stmt = stmt.where(
            ResolutionOutboundDraftRow.execution_id == query.execution_id
        )
    if query.dispatch_id is not None:
        stmt = stmt.where(ResolutionOutboundDraftRow.dispatch_id == query.dispatch_id)
    if query.status is not None:
        stmt = stmt.where(ResolutionOutboundDraftRow.status == query.status)
    return stmt


def _record_to_row(record: ResolutionProposalRecord) -> ResolutionProposalRow:
    return ResolutionProposalRow(
        proposal_id=UUID(str(record.proposal_id)),
        tenant_id=record.tenant_id,
        session_id=_required_uuid(record.session_id, "session_id"),
        execution_id=_required_uuid(record.execution_id, "execution_id"),
        dispatch_id=UUID(record.dispatch_id),
        diagnostic_event_id=(
            UUID(record.diagnostic_event_id)
            if record.diagnostic_event_id is not None
            else None
        ),
        proposed_customer_reply=record.proposed_customer_reply,
        source_language=record.source_language,
        resolution_category=record.resolution_category,
        confidence=record.confidence,
        recommended_actions=[
            dict(action) for action in record.recommended_actions
        ],
        evidence=[dict(item) for item in record.evidence],
        supervisor_verdict=record.supervisor_verdict.value,
        governance_verdict=record.governance_verdict.value,
        governance_decision_id=(
            UUID(str(record.governance_decision_id))
            if record.governance_decision_id is not None
            else None
        ),
        autonomy_decision=record.autonomy_decision.value,
        status=record.status.value,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _row_to_record(row: ResolutionProposalRow) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(row.proposal_id),
        tenant_id=row.tenant_id,
        session_id=(
            str(row.session_id) if row.session_id is not None else None
        ),
        execution_id=(
            str(row.execution_id) if row.execution_id is not None else None
        ),
        dispatch_id=str(row.dispatch_id),
        diagnostic_event_id=(
            str(row.diagnostic_event_id)
            if row.diagnostic_event_id is not None
            else None
        ),
        proposed_customer_reply=row.proposed_customer_reply,
        source_language=row.source_language,
        resolution_category=row.resolution_category,
        confidence=row.confidence,
        recommended_actions=tuple(_as_list_of_dict(row.recommended_actions)),
        evidence=tuple(_as_list_of_dict(row.evidence)),
        supervisor_verdict=ResolutionSupervisorVerdict(row.supervisor_verdict),
        governance_verdict=ResolutionGovernanceVerdict(row.governance_verdict),
        governance_decision_id=row.governance_decision_id,
        autonomy_decision=ResolutionAutonomyDecision(row.autonomy_decision),
        status=ResolutionProposalStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _draft_record_to_row(
    record: ResolutionOutboundDraftRecord,
) -> ResolutionOutboundDraftRow:
    return ResolutionOutboundDraftRow(
        draft_id=UUID(str(record.draft_id)),
        tenant_id=record.tenant_id,
        proposal_id=UUID(str(record.proposal_id)),
        session_id=record.session_id,
        execution_id=record.execution_id,
        dispatch_id=record.dispatch_id,
        diagnostic_event_id=record.diagnostic_event_id,
        governance_decision_id=(
            UUID(str(record.governance_decision_id))
            if record.governance_decision_id is not None
            else None
        ),
        status=record.status.value,
        draft_body=record.draft_body,
        draft_body_sha256=record.draft_body_sha256,
        metadata_json=dict(record.metadata),
        resolution_category=record.resolution_category,
        confidence=record.confidence,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _required_uuid(value: str | None, field_name: str) -> UUID:
    if value is None:
        raise ValueError(
            f"resolution proposal {field_name} is required for writes"
        )
    return UUID(value)


def _draft_row_to_record(
    row: ResolutionOutboundDraftRow,
) -> ResolutionOutboundDraftRecord:
    return ResolutionOutboundDraftRecord(
        draft_id=as_resolution_outbound_draft_id(row.draft_id),
        tenant_id=row.tenant_id,
        proposal_id=as_resolution_proposal_id(row.proposal_id),
        session_id=row.session_id,
        execution_id=row.execution_id,
        dispatch_id=row.dispatch_id,
        diagnostic_event_id=row.diagnostic_event_id,
        governance_decision_id=row.governance_decision_id,
        status=ResolutionOutboundDraftStatus(row.status),
        draft_body=row.draft_body,
        draft_body_sha256=row.draft_body_sha256,
        metadata=_as_dict(row.metadata_json),
        resolution_category=row.resolution_category,
        confidence=row.confidence,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str,
) -> None:
    if tenant_id != expected_tenant_id:
        raise ResolutionPersistenceError(
            "resolution proposal tenant_id does not match expected_tenant_id"
        )


def _as_list_of_dict(value: object) -> list[dict[str, Any]]:
    if not _is_object_list(value):
        return []

    items: list[dict[str, Any]] = []
    for item in value:
        if not _is_object_mapping(item):
            continue
        copied_item: dict[str, Any] = {}
        for key, item_value in item.items():
            copied_item[str(key)] = item_value
        items.append(copied_item)
    return items


def _as_dict(value: object) -> dict[str, Any]:
    if not _is_object_mapping(value):
        return {}
    return {str(key): item_value for key, item_value in value.items()}


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_object_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


__all__ = ["PostgresResolutionProposalPersistence"]
