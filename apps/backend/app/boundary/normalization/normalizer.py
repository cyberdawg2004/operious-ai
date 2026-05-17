"""`BoundaryNormalizer` — adapter orchestration + canonicalisation.

The normaliser is a thin orchestrator: it asks an adapter to
classify + extract canonical fields from a raw payload, then
canonicalises the output through `canonicalize_payload`.

The normaliser does NOT:

* select adapters (caller passes one in),
* authenticate (adapters are responsible),
* persist (caller does that),
* dispatch (substrate isolation).

This is a pure function from `(adapter, payload, source) →
BoundaryNormalizationResult` modulo the adapter's own behaviour.
"""

from __future__ import annotations

from app.boundary.enums import BoundaryNormalizationStatus
from app.boundary.exceptions import (
    BoundaryAuthenticationError,
    BoundaryNormalizationError,
)
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.normalization.canonicalize import (
    canonicalize_metadata,
    canonicalize_payload,
)


class BoundaryNormalizer:
    """Thin orchestrator around an ingress adapter.

    The class is stateless; constructor takes nothing. Pass one
    instance around as a dependency or create per-call — both are
    safe.
    """

    __slots__ = ()

    def normalize(
        self,
        *,
        adapter,  # type: ignore[no-untyped-def]
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        """Run an adapter and canonicalise its output.

        Adapter exceptions are translated into a result-bearing
        error: `BoundaryAuthenticationError` →
        `UNAUTHENTICATED`; any other exception →
        `ADAPTER_ERROR`.
        """
        try:
            raw = adapter.normalize(source=source, payload=payload)
        except BoundaryAuthenticationError as exc:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.UNAUTHENTICATED,
                error=str(exc),
            )
        except BoundaryNormalizationError as exc:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.ADAPTER_ERROR,
                error=(
                    f"adapter {adapter.name!r} raised "
                    f"{exc.__class__.__name__}: {exc}"
                ),
            )

        if not isinstance(raw, BoundaryNormalizationResult):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.ADAPTER_ERROR,
                error=(
                    f"adapter {adapter.name!r} returned an unexpected "
                    f"type: {type(raw)!r}"
                ),
            )

        # Always re-canonicalise — adapters MAY skip this, the
        # substrate MUST guarantee deterministic output.
        return BoundaryNormalizationResult(
            status=raw.status,
            message_type=raw.message_type,
            external_message_id=raw.external_message_id,
            external_conversation_id=raw.external_conversation_id,
            external_emitted_at=raw.external_emitted_at,
            canonical_payload=canonicalize_payload(
                raw.canonical_payload
            )
            if raw.canonical_payload is not None
            else {},
            error=raw.error,
            metadata=canonicalize_metadata(raw.metadata),
        )


__all__ = ["BoundaryNormalizer"]
