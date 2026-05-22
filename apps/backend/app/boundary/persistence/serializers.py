"""Runtime → persistence serialisation helpers."""

from __future__ import annotations

from datetime import datetime

from app.boundary.contracts.results import (
    BoundaryEgressResult,
    BoundaryIngressResult,
)
from app.boundary.envelopes import (
    BoundaryEgressEnvelope,
    BoundaryIngressEnvelope,
)
from app.boundary.enums import (
    BoundaryNormalizationStatus,
)
from app.boundary.identity import (
    as_external_conversation_id,
    as_external_message_id,
)
from app.boundary.models.event import ExternalBoundaryEvent
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.source import BoundarySource
from app.boundary.persistence.records import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
)


def ingress_result_to_record(
    result: BoundaryIngressResult,
    *,
    received_at: datetime | None = None,
) -> BoundaryIngressRecord:
    """Project a `BoundaryIngressResult` into an immutable record."""
    event = result.event
    received = received_at or (
        event.received_at if event is not None else result.started_at
    )
    return BoundaryIngressRecord(
        ingress_id=result.ingress_id,
        direction=result.direction,
        runtime_instance_id=result.runtime_instance_id,
        sequence=result.sequence,
        source_type=(
            event.source.source_type
            if event is not None
            else _infer_source_type_from_metadata(result)
        ),
        source_id=(
            event.source.source_id
            if event is not None
            else str(
                result.metadata.get(
                    "boundary.source_id", "unknown"
                )
            )
        ),
        tenant_id=result.tenant_id,
        adapter_name=result.adapter_name,
        normalization_status=result.normalization.status,
        message_type=result.normalization.message_type,
        replay_disposition=result.replay_disposition,
        replay_key=result.replay_key,
        event_id=result.event_id,
        original_event_id=result.original_event_id,
        external_message_id=result.normalization.external_message_id,
        external_conversation_id=(
            result.normalization.external_conversation_id
        ),
        external_emitted_at=result.normalization.external_emitted_at,
        received_at=received,
        started_at=result.started_at,
        ended_at=result.ended_at,
        latency_ms=result.latency_ms,
        correlation_id=result.correlation_id,
        request_id=result.request_id,
        canonical_payload=dict(
            result.normalization.canonical_payload
        ),
        error=result.error,
        metadata=dict(result.metadata),
    )


def ingress_envelope_to_record(
    envelope: BoundaryIngressEnvelope,
) -> BoundaryIngressRecord | None:
    if envelope.result is None:
        return None
    return ingress_result_to_record(envelope.result)


def ingress_record_to_result(
    record: BoundaryIngressRecord,
) -> BoundaryIngressResult:
    """Rehydrate a persisted ingress record into runtime result shape."""
    normalization = BoundaryNormalizationResult(
        status=record.normalization_status,
        message_type=record.message_type,
        external_message_id=record.external_message_id,
        external_conversation_id=record.external_conversation_id,
        external_emitted_at=record.external_emitted_at,
        canonical_payload=dict(record.canonical_payload),
        error=(
            record.error
            if record.normalization_status
            is not BoundaryNormalizationStatus.OK
            else None
        ),
        metadata=dict(record.metadata),
    )
    event = None
    if (
        record.normalization_status is BoundaryNormalizationStatus.OK
        and record.event_id is not None
        and record.external_message_id
    ):
        event = ExternalBoundaryEvent(
            event_id=record.event_id,
            source=BoundarySource(
                source_type=record.source_type,
                source_id=record.source_id,
                tenant_id=record.tenant_id,
            ),
            message_type=record.message_type,
            external_message_id=as_external_message_id(
                record.external_message_id
            ),
            canonical_payload=dict(record.canonical_payload),
            received_at=record.received_at,
            external_conversation_id=(
                as_external_conversation_id(
                    record.external_conversation_id
                )
                if record.external_conversation_id
                else None
            ),
            external_emitted_at=record.external_emitted_at,
            adapter_name=record.adapter_name,
            metadata=dict(record.metadata),
        )
    return BoundaryIngressResult(
        ingress_id=record.ingress_id,
        direction=record.direction,
        normalization=normalization,
        replay_disposition=record.replay_disposition,
        replay_key=record.replay_key,
        adapter_name=record.adapter_name,
        sequence=record.sequence,
        runtime_instance_id=record.runtime_instance_id,
        started_at=record.started_at,
        ended_at=record.ended_at,
        latency_ms=record.latency_ms,
        event_id=record.event_id,
        original_event_id=record.original_event_id,
        event=event,
        correlation_id=record.correlation_id,
        request_id=record.request_id,
        tenant_id=record.tenant_id,
        error=record.error,
        metadata=dict(record.metadata),
    )


def egress_result_to_record(
    result: BoundaryEgressResult,
    *,
    source_type,  # type: ignore[no-untyped-def]
    source_id: str,
) -> BoundaryEgressRecord:
    """Project a `BoundaryEgressResult` into an immutable record.

    The runtime supplies the typed `source_type` + `source_id`
    explicitly because the result itself is direction/lineage-only;
    source identity sits on the request.
    """
    payload = result.payload
    return BoundaryEgressRecord(
        egress_id=result.egress_id,
        direction=result.direction,
        runtime_instance_id=result.runtime_instance_id,
        sequence=result.sequence,
        source_type=source_type,
        source_id=source_id,
        tenant_id=result.tenant_id,
        adapter_name=result.adapter_name,
        payload_body=(payload.body if payload is not None else None),
        payload_content_type=(
            payload.content_type if payload is not None else None
        ),
        payload_target_uri=(
            payload.target_uri if payload is not None else None
        ),
        payload_method=(
            payload.method if payload is not None else None
        ),
        payload_headers=dict(
            payload.headers if payload is not None else {}
        ),
        translated_at=result.translated_at,
        started_at=result.started_at,
        ended_at=result.ended_at,
        latency_ms=result.latency_ms,
        correlation_id=result.correlation_id,
        request_id=result.request_id,
        error=result.error,
        metadata=dict(result.metadata),
    )


def egress_envelope_to_record(
    envelope: BoundaryEgressEnvelope,
    *,
    source_type,  # type: ignore[no-untyped-def]
    source_id: str,
) -> BoundaryEgressRecord | None:
    if envelope.result is None:
        return None
    return egress_result_to_record(
        envelope.result,
        source_type=source_type,
        source_id=source_id,
    )


def _infer_source_type_from_metadata(
    result: BoundaryIngressResult,
):  # type: ignore[no-untyped-def]
    """Best-effort fallback when the result has no event."""
    from app.boundary.enums import BoundarySourceType

    raw = result.metadata.get("boundary.source_type")
    if isinstance(raw, str):
        try:
            return BoundarySourceType(raw)
        except ValueError:
            pass
    return BoundarySourceType.GENERIC


__all__ = [
    "egress_envelope_to_record",
    "egress_result_to_record",
    "ingress_envelope_to_record",
    "ingress_record_to_result",
    "ingress_result_to_record",
]
