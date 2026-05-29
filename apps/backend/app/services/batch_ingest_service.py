"""Batch-safe boundary ingestion service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, cast

from app.api.v1.schemas.ingress import (
    BatchIngestItem,
    BatchIngestItemResult,
    BatchIngestResponse,
    BatchItemStatus,
)
from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryIngressId,
    as_ingress_id,
    make_boundary_id,
)
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models.normalization import BoundaryNormalizationResult
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.normalization.canonicalize import canonicalize_payload
from app.boundary.persistence import (
    BoundaryIngressRecord,
    BoundaryPersistenceProtocol,
    ingress_result_to_record,
)
from app.boundary.registry import BoundaryAdapterRegistry
from app.identity import AuthorityContext


class BatchDispatchService(Protocol):
    async def dispatch(self, ingress_id: str, tenant_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class _Candidate:
    index: int
    item: BatchIngestItem
    boundary_id: str
    ingress_id: BoundaryIngressId
    record: BoundaryIngressRecord


class BatchIngestService:
    """Creates boundary records in bulk and dispatches accepted items."""

    def __init__(
        self,
        *,
        boundary_repository: BoundaryPersistenceProtocol,
        dispatch_service: BatchDispatchService,
    ) -> None:
        self._boundary_repository = boundary_repository
        self._dispatch_service = dispatch_service

    async def process_batch(
        self,
        *,
        items: Sequence[BatchIngestItem],
        tenant_id: str,
    ) -> BatchIngestResponse:
        runtime = BoundaryIngressRuntime(
            adapters=BoundaryAdapterRegistry((_BatchIngestAdapter(),)),
            persistence=None,
        )
        results: dict[int, BatchIngestItemResult] = {}
        candidates: list[_Candidate] = []
        seen_boundary_ids: set[str] = set()

        for index, item in enumerate(items):
            rejected = _rejection_reason(item=item, tenant_id=tenant_id)
            if rejected is not None:
                results[index] = BatchIngestItemResult(
                    index=index,
                    external_message_id=item.external_message_id,
                    status=BatchItemStatus.REJECTED,
                    reason=rejected,
                )
                continue

            channel_type = _normalize_channel_type(item.channel_type)
            boundary_id = make_boundary_id(
                tenant_id=tenant_id,
                channel_type=channel_type,
                source_id=item.source_id,
                external_message_id=item.external_message_id,
            )
            if boundary_id in seen_boundary_ids:
                results[index] = BatchIngestItemResult(
                    index=index,
                    external_message_id=item.external_message_id,
                    status=BatchItemStatus.DUPLICATE,
                    boundary_id=boundary_id,
                )
                continue
            seen_boundary_ids.add(boundary_id)

            record = await _record_from_runtime(
                runtime=runtime,
                item=item,
                tenant_id=tenant_id,
                channel_type=channel_type,
                boundary_id=boundary_id,
            )
            if record is None:
                results[index] = BatchIngestItemResult(
                    index=index,
                    external_message_id=item.external_message_id,
                    status=BatchItemStatus.REJECTED,
                    boundary_id=None,
                    reason="boundary normalization failed",
                )
                continue
            candidates.append(
                _Candidate(
                    index=index,
                    item=item,
                    boundary_id=boundary_id,
                    ingress_id=as_ingress_id(boundary_id),
                    record=record,
                )
            )

        candidate_ids = [candidate.ingress_id for candidate in candidates]
        existing_ids: set[BoundaryIngressId] = set()
        if candidate_ids:
            existing_ids = (
                await self._boundary_repository.get_existing_ingress_ids(
                    candidate_ids,
                    expected_tenant_id=tenant_id,
                )
            )
        insertable = [
            candidate.record
            for candidate in candidates
            if candidate.ingress_id not in existing_ids
        ]
        inserted_ids: set[BoundaryIngressId] = set()
        if insertable:
            inserted_ids = (
                await self._boundary_repository.bulk_insert_ingress_records(
                    insertable
                )
            )

        accepted: list[_Candidate] = []
        for candidate in candidates:
            if candidate.ingress_id in existing_ids:
                results[candidate.index] = BatchIngestItemResult(
                    index=candidate.index,
                    external_message_id=candidate.item.external_message_id,
                    status=BatchItemStatus.DUPLICATE,
                    boundary_id=candidate.boundary_id,
                )
                continue
            if candidate.ingress_id not in inserted_ids:
                results[candidate.index] = BatchIngestItemResult(
                    index=candidate.index,
                    external_message_id=candidate.item.external_message_id,
                    status=BatchItemStatus.DUPLICATE,
                    boundary_id=candidate.boundary_id,
                )
                continue
            results[candidate.index] = BatchIngestItemResult(
                index=candidate.index,
                external_message_id=candidate.item.external_message_id,
                status=BatchItemStatus.ACCEPTED,
                boundary_id=candidate.boundary_id,
            )
            accepted.append(candidate)

        for candidate in accepted:
            await self._dispatch_service.dispatch(
                ingress_id=candidate.boundary_id,
                tenant_id=tenant_id,
            )

        ordered_results = [results[index] for index in range(len(items))]
        return BatchIngestResponse(
            total=len(items),
            accepted=sum(
                result.status is BatchItemStatus.ACCEPTED
                for result in ordered_results
            ),
            duplicate=sum(
                result.status is BatchItemStatus.DUPLICATE
                for result in ordered_results
            ),
            rejected=sum(
                result.status is BatchItemStatus.REJECTED
                for result in ordered_results
            ),
            results=ordered_results,
        )


class _BatchIngestAdapter(BaseIngressAdapter):
    DEFAULT_NAME = "batch_ingest_adapter"

    def __init__(self) -> None:
        super().__init__(
            name=self.DEFAULT_NAME,
            source_type=BoundarySourceType.GENERIC,
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = payload.body
        if not isinstance(body, Mapping):
            return _malformed("batch payload must be a mapping")
        body_map = cast(Mapping[str, object], body)
        external_message_id = body_map.get("external_message_id")
        text = body_map.get("body")
        if not isinstance(external_message_id, str) or not external_message_id:
            return _malformed("missing external_message_id")
        if not isinstance(text, str) or not text.strip():
            return _malformed("body must not be empty")
        raw_metadata = body_map.get("metadata")
        channel_type = str(body_map.get("channel_type") or "")
        emitted_at = _parse_received_at(body_map.get("received_at"))
        canonical_payload: dict[str, object] = {
            "channel_type": channel_type,
            "source_id": source.source_id,
            "external_message_id": external_message_id,
            "subject": body_map.get("subject"),
            "body": text,
            "received_at": emitted_at.isoformat() if emitted_at else None,
            "metadata": canonicalize_payload(
                (
                    cast(Mapping[str, object], raw_metadata)
                    if isinstance(raw_metadata, Mapping)
                    else {}
                )
            ),
        }
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=BoundaryMessageType.MESSAGE_RECEIVED,
            external_message_id=external_message_id,
            external_conversation_id=source.source_id,
            external_emitted_at=emitted_at,
            canonical_payload=canonical_payload,
            metadata={
                "batch.channel_type": channel_type,
                "batch.source_id": source.source_id,
            },
        )


async def _record_from_runtime(
    *,
    runtime: BoundaryIngressRuntime,
    item: BatchIngestItem,
    tenant_id: str,
    channel_type: str,
    boundary_id: str,
) -> BoundaryIngressRecord | None:
    received_at = _normalize_datetime(item.received_at)
    envelope = await runtime.ingest(
        BoundaryIngressRequest(
            source=BoundarySource(
                source_type=_source_type_for_channel(channel_type),
                source_id=item.source_id,
                tenant_id=tenant_id,
                display_name=f"batch {channel_type}",
                metadata={
                    "batch.channel_type": channel_type,
                },
            ),
            adapter_name=_BatchIngestAdapter.DEFAULT_NAME,
            payload=IngressPayload(
                body={
                    "channel_type": channel_type,
                    "source_id": item.source_id,
                    "external_message_id": item.external_message_id,
                    "subject": item.subject,
                    "body": item.body,
                    "received_at": received_at.isoformat(),
                    "metadata": canonicalize_payload(item.metadata),
                },
                content_type="application/json",
            ),
            correlation_id=item.external_message_id,
            request_id=item.external_message_id,
            ingress_id_override=as_ingress_id(boundary_id),
            authority=AuthorityContext.from_raw(tenant_id=tenant_id),
            metadata={
                "batch.channel_type": channel_type,
                "batch.source_id": item.source_id,
                "batch.external_message_id": item.external_message_id,
                "batch.received_at": received_at.isoformat(),
                "batch.item_metadata": canonicalize_payload(item.metadata),
            },
        )
    )
    if envelope.error is not None or envelope.result is None:
        return None
    if envelope.result.normalization.status is not BoundaryNormalizationStatus.OK:
        return None
    return ingress_result_to_record(envelope.result, received_at=received_at)


def _rejection_reason(
    *,
    item: BatchIngestItem,
    tenant_id: str,
) -> str | None:
    if item.tenant_id is not None and item.tenant_id != tenant_id:
        return "tenant_id does not match request authority"
    if _normalize_channel_type(item.channel_type) not in _CHANNEL_SOURCE_TYPES:
        return "unsupported channel_type"
    if not item.source_id.strip():
        return "source_id must not be empty"
    if not item.external_message_id.strip():
        return "external_message_id must not be empty"
    if not item.body.strip():
        return "body must not be empty"
    return None


def _source_type_for_channel(channel_type: str) -> BoundarySourceType:
    return _CHANNEL_SOURCE_TYPES[channel_type]


def _normalize_channel_type(channel_type: str) -> str:
    return channel_type.strip().lower()


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_received_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if not isinstance(value, str):
        return None
    try:
        return _normalize_datetime(
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except ValueError:
        return None


def _malformed(reason: str) -> BoundaryNormalizationResult:
    return BoundaryNormalizationResult(
        status=BoundaryNormalizationStatus.MALFORMED,
        error=reason,
    )


_CHANNEL_SOURCE_TYPES: dict[str, BoundarySourceType] = {
    "email": BoundarySourceType.EMAIL,
    "whatsapp": BoundarySourceType.WHATSAPP,
    "shopify": BoundarySourceType.GENERIC,
    "voice": BoundarySourceType.TWILIO_VOICE,
}


__all__ = ["BatchDispatchService", "BatchIngestService"]
