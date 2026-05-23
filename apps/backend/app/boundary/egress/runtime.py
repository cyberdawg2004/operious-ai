"""`BoundaryEgressRuntime` — deterministic → external translation.

The egress runtime translates an opaque caller-supplied artifact
into a canonical `EgressPayload` and persists the audit record.
It does NOT actually transmit; transmission belongs to the
orchestration layer OUTSIDE this package.

Sprint M discipline:

* `emit()` NEVER raises — failures fold onto the envelope.
* No retries. No scheduling. No fanout.
* The substrate is purely a translator + ledger.
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
from app.core.deterministic_identity import derive_runtime_id
from app.boundary.adapters.base import BaseEgressAdapter
from app.boundary.contracts.requests import (
    BoundaryEgressRequest,
)
from app.boundary.contracts.results import (
    BoundaryEgressResult,
)
from app.boundary.envelopes import BoundaryEgressEnvelope
from app.boundary.enums import BoundaryDirection
from app.boundary.exceptions import (
    BoundaryConfigurationError,
)
from app.boundary.identity import (
    BoundaryEgressId,
    generate_egress_id,
)
from app.boundary.persistence.repository import (
    BoundaryPersistenceProtocol,
)
from app.boundary.persistence.serializers import (
    egress_result_to_record,
)
from app.boundary.registry.registry import (
    BoundaryAdapterRegistry,
)
from app.boundary.taxonomy import BoundaryMetadataKey
from app.boundary.tracing import BoundaryTrace

_logger = logging.getLogger(__name__)
_RUNTIME_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe506002")


class BoundaryEgressRuntime:
    """Translation substrate: runtime artifact → outbound payload."""

    __slots__ = (
        "_adapters",
        "_persistence",
        "_runtime_instance_id",
        "_sequence",
    )

    def __init__(
        self,
        *,
        adapters: BoundaryAdapterRegistry,
        persistence: BoundaryPersistenceProtocol | None = None,
    ) -> None:
        self._adapters = adapters
        self._persistence = persistence
        self._runtime_instance_id = derive_runtime_id(
            namespace=_RUNTIME_NAMESPACE,
            tenant_id=None,
            seed_components=(
                "boundary_egress_runtime",
                adapters.names(direction=BoundaryDirection.EGRESS),
            ),
        )
        self._sequence: int = 0

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    @property
    def adapters(self) -> BoundaryAdapterRegistry:
        return self._adapters

    @property
    def persistence(
        self,
    ) -> BoundaryPersistenceProtocol | None:
        return self._persistence

    async def emit(
        self, request: BoundaryEgressRequest
    ) -> BoundaryEgressEnvelope:
        """Translate one runtime artifact into an outbound payload."""
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        egress_id = (
            request.egress_id_override
            if request.egress_id_override is not None
            else generate_egress_id()
        )
        # Wedge 2.75-β: singular authority resolution at the egress
        # boundary. ``BoundarySource.tenant_id`` is treated as the
        # OBSERVED axis; typed ``request.authority`` (B2) wins when
        # present. Egress-time governance gates and persistence
        # records consume ``resolution.tenant_id`` instead of
        # cross-reading ``request.source.tenant_id``.
        resolution = request_authority_resolution(
            request,
            observed_tenant_id=request.source.tenant_id,
        )

        # Resolve the named adapter (only required when
        # `prebuilt_payload` is absent).
        adapter_name: str
        adapter: BaseEgressAdapter | None = None
        if request.prebuilt_payload is None:
            try:
                adapter = self._resolve_adapter(request.adapter_name)
                adapter_name = adapter.name
            except BoundaryConfigurationError as exc:
                return self._failed_envelope(
                    request=request,
                    egress_id=egress_id,
                    adapter_name=request.adapter_name,
                    started_at=started_at,
                    t0=t0,
                    error=exc,
                    reason=f"adapter resolution failed: {exc}",
                    resolution=resolution,
                )
        else:
            adapter_name = request.adapter_name

        # Translate (or use the prebuilt payload).
        framework_error: BaseException | None = None
        payload = request.prebuilt_payload
        translated_at = datetime.now(tz=timezone.utc)
        if payload is None:
            assert adapter is not None  # narrow for type checkers
            try:
                payload = adapter.serialize(
                    source=request.source,
                    artifact=request.artifact,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "egress adapter %s raised; folding onto envelope",
                    adapter_name,
                )
                framework_error = exc
                payload = None
            translated_at = datetime.now(tz=timezone.utc)

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self._sequence += 1
        sequence = self._sequence

        result = BoundaryEgressResult(
            egress_id=egress_id,
            direction=BoundaryDirection.EGRESS,
            adapter_name=adapter_name,
            sequence=sequence,
            runtime_instance_id=self._runtime_instance_id,
            translated_at=translated_at,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            payload=payload,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            error=(
                f"{framework_error.__class__.__name__}: "
                f"{framework_error}"
                if framework_error is not None
                else None
            ),
            metadata=self._build_metadata(
                request=request,
                egress_id=egress_id,
                adapter_name=adapter_name,
                resolution=resolution,
            ),
        )

        trace = BoundaryTrace(
            direction=BoundaryDirection.EGRESS,
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
            egress_id=egress_id,
            error=result.error,
            tenant_authority_source=resolution.source.value,
        )

        if self._persistence is not None:
            try:
                await self._persistence.save_egress(
                    egress_result_to_record(
                        result,
                        source_type=request.source.source_type,
                        source_id=request.source.source_id,
                    )
                )
            except Exception as persistence_exc:  # noqa: BLE001
                _logger.exception(
                    "boundary persistence failed for egress_id=%s",
                    egress_id,
                )
                framework_error = (
                    framework_error or persistence_exc
                )

        return BoundaryEgressEnvelope(
            trace=trace, result=result, error=framework_error
        )

    # ─── helpers ─────────────────────────────────────────────────

    def _resolve_adapter(self, name: str) -> BaseEgressAdapter:
        if not self._adapters.has(
            name, direction=BoundaryDirection.EGRESS
        ):
            raise BoundaryConfigurationError(
                f"unknown egress adapter: {name!r}"
            )
        adapter = self._adapters.get(
            name, direction=BoundaryDirection.EGRESS
        )
        if not isinstance(adapter, BaseEgressAdapter):
            raise BoundaryConfigurationError(
                f"adapter {name!r} is not a BaseEgressAdapter"
            )
        return adapter

    @staticmethod
    def _build_metadata(
        *,
        request: BoundaryEgressRequest,
        egress_id: BoundaryEgressId,
        adapter_name: str,
        resolution: AuthorityResolution,
    ) -> dict[str, object]:
        meta: dict[str, object] = dict(request.metadata)
        meta[BoundaryMetadataKey.DIRECTION.value] = (
            BoundaryDirection.EGRESS.value
        )
        meta[BoundaryMetadataKey.EGRESS_ID.value] = str(egress_id)
        meta[BoundaryMetadataKey.SOURCE_TYPE.value] = (
            request.source.source_type.value
        )
        meta[BoundaryMetadataKey.SOURCE_ID.value] = (
            request.source.source_id
        )
        meta[BoundaryMetadataKey.ADAPTER_NAME.value] = (
            adapter_name
        )
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

    def _failed_envelope(
        self,
        *,
        request: BoundaryEgressRequest,
        egress_id: BoundaryEgressId,
        adapter_name: str,
        started_at: datetime,
        t0: float,
        error: BoundaryConfigurationError,
        reason: str,
        resolution: AuthorityResolution,
    ) -> BoundaryEgressEnvelope:
        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        trace = BoundaryTrace(
            direction=BoundaryDirection.EGRESS,
            runtime_instance_id=self._runtime_instance_id,
            sequence=self._sequence,
            source_type=request.source.source_type,
            source_id=request.source.source_id,
            adapter_name=adapter_name,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            egress_id=egress_id,
            error=reason,
            tenant_authority_source=resolution.source.value,
        )
        return BoundaryEgressEnvelope(
            trace=trace, result=None, error=error
        )


__all__ = ["BoundaryEgressRuntime"]
