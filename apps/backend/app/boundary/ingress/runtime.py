"""`BoundaryIngressRuntime` — external → deterministic translation.

Sprint M discipline:

* This is a **translation substrate**, not an orchestration runtime.
* `ingest()` NEVER raises — failures fold onto the envelope.
* The lifecycle is deterministic and bounded::

      validate → adapter.normalize → derive ids
      → replay-classify → build event → record observation
      → persist → return

* No agent invocation. No coordination dispatch. No retry loops.
  No autonomous recovery.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from app.identity import (
    AuthorityResolution,
    request_authority_resolution,
)
from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.contracts.requests import (
    BoundaryIngressRequest,
)
from app.boundary.contracts.results import (
    BoundaryIngressResult,
)
from app.boundary.envelopes import BoundaryIngressEnvelope
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
)
from app.boundary.exceptions import (
    BoundaryConfigurationError,
)
from app.boundary.identity import (
    BoundaryEventId,
    BoundaryIngressId,
    derive_event_id,
    derive_replay_key,
    generate_ingress_id,
)
from app.boundary.idempotency.detector import (
    BoundaryReplayDetector,
)
from app.boundary.idempotency.registry import (
    BoundaryIdempotencyRegistry,
)
from app.boundary.models.event import ExternalBoundaryEvent
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.normalization.canonicalize import (
    content_fingerprint,
)
from app.boundary.normalization.normalizer import (
    BoundaryNormalizer,
)
from app.boundary.persistence.repository import (
    BoundaryPersistenceProtocol,
)
from app.boundary.persistence.serializers import (
    ingress_result_to_record,
)
from app.boundary.registry.registry import (
    BoundaryAdapterRegistry,
)
from app.boundary.taxonomy import BoundaryMetadataKey
from app.boundary.tracing import BoundaryTrace

_logger = logging.getLogger(__name__)


class BoundaryIngressRuntime:
    """Translation substrate: external delivery → canonical event."""

    __slots__ = (
        "_adapters",
        "_normalizer",
        "_idempotency",
        "_detector",
        "_persistence",
        "_runtime_instance_id",
        "_sequence",
    )

    def __init__(
        self,
        *,
        adapters: BoundaryAdapterRegistry,
        idempotency: BoundaryIdempotencyRegistry,
        normalizer: BoundaryNormalizer | None = None,
        detector: BoundaryReplayDetector | None = None,
        persistence: BoundaryPersistenceProtocol | None = None,
    ) -> None:
        self._adapters = adapters
        self._idempotency = idempotency
        self._normalizer = normalizer or BoundaryNormalizer()
        self._detector = detector or BoundaryReplayDetector()
        self._persistence = persistence
        self._runtime_instance_id: uuid.UUID = uuid.uuid4()
        self._sequence: int = 0

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    @property
    def adapters(self) -> BoundaryAdapterRegistry:
        return self._adapters

    @property
    def idempotency(self) -> BoundaryIdempotencyRegistry:
        return self._idempotency

    @property
    def persistence(
        self,
    ) -> BoundaryPersistenceProtocol | None:
        return self._persistence

    async def ingest(
        self, request: BoundaryIngressRequest
    ) -> BoundaryIngressEnvelope:
        """Translate one inbound delivery to a canonical event."""
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        ingress_id = (
            request.ingress_id_override
            if request.ingress_id_override is not None
            else generate_ingress_id()
        )
        # Wedge 2.75-β: singular authority resolution at the
        # boundary runtime. Replaces every ``request.source.tenant_id``
        # read below so the typed-ingress surface (Wedge B2) and the
        # legacy ``BoundarySource``-derived tenant collapse into one
        # ``AuthorityResolution`` with explicit attribution recorded
        # on the trace via ``tenant_authority_source``. The boundary
        # source's ``tenant_id`` is treated as the OBSERVED axis (it
        # is what the inbound delivery declared); typed
        # ``request.authority`` still wins when present, so an
        # operator that mints an ``AuthorityContext`` at the HTTP
        # ingress middleware overrides whatever the external source
        # claimed.
        resolution = request_authority_resolution(
            request,
            observed_tenant_id=request.source.tenant_id,
        )

        # Resolve the named adapter.
        try:
            adapter = self._resolve_adapter(request.adapter_name)
        except BoundaryConfigurationError as exc:
            return self._failed_envelope(
                request=request,
                ingress_id=ingress_id,
                started_at=started_at,
                t0=t0,
                error=exc,
                reason=f"adapter resolution failed: {exc}",
                normalization=BoundaryNormalizationResult(
                    status=BoundaryNormalizationStatus.ADAPTER_ERROR,
                    error=str(exc),
                ),
                resolution=resolution,
            )

        # 1. Normalise.
        normalization = self._normalizer.normalize(
            adapter=adapter,
            source=request.source,
            payload=request.payload,
        )

        # 2. Replay classification — only meaningful if normalisation
        #    surfaced an external_message_id we can deterministically
        #    key on. Otherwise the disposition is INVALID_KEY.
        replay_key = None
        if (
            normalization.is_ok
            and normalization.external_message_id
        ):
            try:
                replay_key = derive_replay_key(
                    source_type=request.source.source_type.value,
                    external_message_id=(
                        normalization.external_message_id
                    ),
                    tenant_id=resolution.tenant_id,
                )
            except ValueError:
                replay_key = None
        decision = await self._detector.classify(
            replay_key=replay_key,
            content_fingerprint=content_fingerprint(
                normalization.canonical_payload
            ),
            registry=self._idempotency,
        )

        # 3. Derive event id.
        event_id: BoundaryEventId | None
        if (
            normalization.is_ok
            and normalization.external_message_id
        ):
            event_id = derive_event_id(
                source_type=request.source.source_type.value,
                external_message_id=(
                    normalization.external_message_id
                ),
                tenant_id=resolution.tenant_id,
            )
        else:
            event_id = None

        # 4. Replay-record bookkeeping. Lineage NEVER changes.
        original_event_id: BoundaryEventId | None = None
        if (
            decision.disposition is BoundaryReplayDisposition.NEW
            and event_id is not None
            and replay_key is not None
        ):
            try:
                await self._idempotency.record_first_seen(
                    replay_key=replay_key,
                    event_id=event_id,
                    source_type=request.source.source_type,
                    external_message_id=(
                        normalization.external_message_id or ""
                    ),
                    tenant_id=resolution.tenant_id,
                    content_fingerprint=content_fingerprint(
                        normalization.canonical_payload
                    ),
                    seen_at=started_at,
                )
            except ValueError:
                # Race — another caller registered the same key
                # between classify and record. Re-classify to pick
                # up the now-existing record.
                existing = await self._idempotency.get(
                    replay_key
                )
                if existing is not None:
                    decision = (
                        await self._detector.classify(
                            replay_key=replay_key,
                            content_fingerprint=content_fingerprint(
                                normalization.canonical_payload
                            ),
                            registry=self._idempotency,
                        )
                    )
                    original_event_id = existing.event_id
                    event_id = existing.event_id
            original_event_id = original_event_id or event_id
        elif (
            decision.disposition
            in {
                BoundaryReplayDisposition.REPLAY_OF_KNOWN,
                BoundaryReplayDisposition.LINEAGE_DRIFT,
            }
            and replay_key is not None
        ):
            await self._idempotency.record_observation(
                replay_key=replay_key,
                disposition=decision.disposition,
                observed_fingerprint=content_fingerprint(
                    normalization.canonical_payload
                ),
                seen_at=started_at,
            )
            original_event_id = decision.original_event_id
            # Replays inherit the ORIGINAL event_id — lineage never
            # rewrites.
            event_id = decision.original_event_id

        # 5. Build canonical event when normalisation succeeded.
        event: ExternalBoundaryEvent | None = None
        if (
            normalization.is_ok
            and event_id is not None
            and normalization.external_message_id
        ):
            from app.boundary.identity import (
                as_external_conversation_id,
                as_external_message_id,
            )

            ext_conv = (
                as_external_conversation_id(
                    normalization.external_conversation_id
                )
                if normalization.external_conversation_id
                else None
            )
            event = ExternalBoundaryEvent(
                event_id=event_id,
                source=request.source,
                message_type=normalization.message_type,
                external_message_id=as_external_message_id(
                    normalization.external_message_id
                ),
                canonical_payload=dict(
                    normalization.canonical_payload
                ),
                received_at=started_at,
                external_conversation_id=ext_conv,
                external_emitted_at=(
                    normalization.external_emitted_at
                ),
                adapter_name=adapter.name,
                metadata=dict(normalization.metadata),
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self._sequence += 1
        sequence = self._sequence

        result = BoundaryIngressResult(
            ingress_id=ingress_id,
            direction=BoundaryDirection.INGRESS,
            normalization=normalization,
            replay_disposition=decision.disposition,
            replay_key=replay_key,
            adapter_name=adapter.name,
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            event_id=event_id,
            original_event_id=original_event_id,
            event=event,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            metadata=self._build_metadata(
                request=request,
                ingress_id=ingress_id,
                event_id=event_id,
                replay_disposition=decision.disposition,
                replay_key=replay_key,
                normalization=normalization,
                adapter_name=adapter.name,
                original_event_id=original_event_id,
                resolution=resolution,
            ),
        )

        trace = self._build_trace(
            request=request,
            ingress_id=ingress_id,
            event_id=event_id,
            adapter_name=adapter.name,
            sequence=sequence,
            normalization=normalization,
            replay_disposition=decision.disposition,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            resolution=resolution,
        )

        framework_error: BaseException | None = None
        if self._persistence is not None:
            try:
                await self._persistence.save_ingress(
                    ingress_result_to_record(result)
                )
            except Exception as persistence_exc:  # noqa: BLE001
                _logger.exception(
                    "boundary persistence failed for "
                    "ingress_id=%s",
                    ingress_id,
                )
                framework_error = persistence_exc

        return BoundaryIngressEnvelope(
            trace=trace, result=result, error=framework_error
        )

    # ─── helpers ─────────────────────────────────────────────────

    def _resolve_adapter(self, name: str) -> BaseIngressAdapter:
        if not self._adapters.has(
            name, direction=BoundaryDirection.INGRESS
        ):
            raise BoundaryConfigurationError(
                f"unknown ingress adapter: {name!r}"
            )
        adapter = self._adapters.get(
            name, direction=BoundaryDirection.INGRESS
        )
        if not isinstance(adapter, BaseIngressAdapter):
            raise BoundaryConfigurationError(
                f"adapter {name!r} is not a BaseIngressAdapter"
            )
        return adapter

    @staticmethod
    def _build_metadata(
        *,
        request: BoundaryIngressRequest,
        ingress_id: BoundaryIngressId,
        event_id: BoundaryEventId | None,
        replay_disposition: BoundaryReplayDisposition,
        replay_key: uuid.UUID | None,
        normalization: BoundaryNormalizationResult,
        adapter_name: str,
        original_event_id: BoundaryEventId | None,
        resolution: AuthorityResolution,
    ) -> dict[str, object]:
        meta: dict[str, object] = dict(request.metadata)
        meta[BoundaryMetadataKey.DIRECTION.value] = (
            BoundaryDirection.INGRESS.value
        )
        meta[BoundaryMetadataKey.INGRESS_ID.value] = str(
            ingress_id
        )
        meta[BoundaryMetadataKey.SOURCE_TYPE.value] = (
            request.source.source_type.value
        )
        meta[BoundaryMetadataKey.SOURCE_ID.value] = (
            request.source.source_id
        )
        meta[BoundaryMetadataKey.ADAPTER_NAME.value] = adapter_name
        meta[BoundaryMetadataKey.NORMALIZATION_STATUS.value] = (
            normalization.status.value
        )
        meta[BoundaryMetadataKey.MESSAGE_TYPE.value] = (
            normalization.message_type.value
        )
        meta[BoundaryMetadataKey.REPLAY_DISPOSITION.value] = (
            replay_disposition.value
        )
        if replay_key is not None:
            meta[BoundaryMetadataKey.REPLAY_KEY.value] = str(
                replay_key
            )
        if event_id is not None:
            meta[BoundaryMetadataKey.EVENT_ID.value] = str(
                event_id
            )
        if original_event_id is not None:
            meta[BoundaryMetadataKey.ORIGINAL_EVENT_ID.value] = (
                str(original_event_id)
            )
        if normalization.external_message_id:
            meta[
                BoundaryMetadataKey.EXTERNAL_MESSAGE_ID.value
            ] = normalization.external_message_id
        if normalization.external_conversation_id:
            meta[
                BoundaryMetadataKey.EXTERNAL_CONVERSATION_ID.value
            ] = normalization.external_conversation_id
        if resolution.tenant_id:
            meta[BoundaryMetadataKey.TENANT_ID.value] = (
                resolution.tenant_id
            )
        if request.correlation_id:
            meta[BoundaryMetadataKey.CORRELATION_ID.value] = (
                request.correlation_id
            )
        if request.request_id:
            meta[BoundaryMetadataKey.REQUEST_ID.value] = (
                request.request_id
            )
        return meta

    def _build_trace(
        self,
        *,
        request: BoundaryIngressRequest,
        ingress_id: BoundaryIngressId,
        event_id: BoundaryEventId | None,
        adapter_name: str,
        sequence: int,
        normalization: BoundaryNormalizationResult,
        replay_disposition: BoundaryReplayDisposition,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
        resolution: AuthorityResolution,
    ) -> BoundaryTrace:
        return BoundaryTrace(
            direction=BoundaryDirection.INGRESS,
            runtime_instance_id=self._runtime_instance_id,
            sequence=sequence,
            source_type=request.source.source_type,
            source_id=request.source.source_id,
            adapter_name=adapter_name,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            external_message_id=(
                normalization.external_message_id
            ),
            external_conversation_id=(
                normalization.external_conversation_id
            ),
            ingress_id=ingress_id,
            event_id=event_id,
            normalization_status=normalization.status,
            replay_disposition=replay_disposition,
            tenant_authority_source=resolution.source.value,
        )

    def _failed_envelope(
        self,
        *,
        request: BoundaryIngressRequest,
        ingress_id: BoundaryIngressId,
        started_at: datetime,
        t0: float,
        error: BoundaryConfigurationError,
        reason: str,
        normalization: BoundaryNormalizationResult,
        resolution: AuthorityResolution,
    ) -> BoundaryIngressEnvelope:
        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        trace = BoundaryTrace(
            direction=BoundaryDirection.INGRESS,
            runtime_instance_id=self._runtime_instance_id,
            sequence=self._sequence,
            source_type=request.source.source_type,
            source_id=request.source.source_id,
            adapter_name=request.adapter_name,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            ingress_id=ingress_id,
            normalization_status=normalization.status,
            replay_disposition=BoundaryReplayDisposition.INVALID_KEY,
            error=reason,
            tenant_authority_source=resolution.source.value,
        )
        return BoundaryIngressEnvelope(
            trace=trace, result=None, error=error
        )


__all__ = ["BoundaryIngressRuntime"]
