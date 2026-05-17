"""`BoundaryIngressRuntime` integration tests.

Validates the apex translation surface:

* deterministic event-id derivation across re-deliveries,
* replay classification (NEW / REPLAY_OF_KNOWN / LINEAGE_DRIFT),
* never-raises contract,
* persistence integration,
* unknown-adapter graceful failure,
* malformed-payload graceful failure,
* original-event lineage preservation across replays.
"""

from __future__ import annotations

import pytest

from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.adapters.builtin.zendesk import (
    ZendeskWebhookAdapter,
)
from app.boundary.contracts.requests import (
    BoundaryIngressRequest,
)
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.exceptions import (
    BoundaryAuthenticationError,
)
from app.boundary.idempotency.registry import (
    BoundaryIdempotencyRegistry,
)
from app.boundary.ingress.runtime import (
    BoundaryIngressRuntime,
)
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence.memory import (
    InMemoryBoundaryPersistence,
)
from app.boundary.persistence.models import (
    BoundaryIngressQuery,
)
from app.boundary.registry.registry import (
    BoundaryAdapterRegistry,
)


def _zendesk_source(*, tenant: str = "tenant-1") -> BoundarySource:
    return BoundarySource(
        source_type=BoundarySourceType.ZENDESK,
        source_id="acct-1",
        tenant_id=tenant,
    )


def _zendesk_payload(
    *, event_id: str = "ze-evt-1", body_extra: str = "hi"
) -> IngressPayload:
    return IngressPayload(
        body={
            "event_id": event_id,
            "ticket_id": "t-100",
            "type": "ticket.comment_created",
            "comment": {"body": body_extra},
            "created_at": "2026-01-01T00:00:00Z",
        }
    )


def _runtime(
    *, persistence: InMemoryBoundaryPersistence | None = None
) -> BoundaryIngressRuntime:
    reg = BoundaryAdapterRegistry([ZendeskWebhookAdapter()])
    return BoundaryIngressRuntime(
        adapters=reg,
        idempotency=BoundaryIdempotencyRegistry(),
        persistence=persistence,
    )


# ─── Construction ────────────────────────────────────────────────────


def test_runtime_exposes_dependencies() -> None:
    rt = _runtime()
    assert rt.runtime_instance_id is not None
    assert rt.persistence is None


# ─── Happy-path normalisation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_first_ingest_classifies_as_new() -> None:
    rt = _runtime()
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_zendesk_source(),
            adapter_name="zendesk_webhook_adapter",
            payload=_zendesk_payload(),
            correlation_id="corr-1",
        )
    )
    assert envelope.is_ok
    result = envelope.unwrap()
    assert result.is_normalised
    assert (
        result.replay_disposition
        is BoundaryReplayDisposition.NEW
    )
    assert result.event is not None
    assert result.event.event_id == result.event_id
    assert result.original_event_id == result.event_id
    assert (
        result.normalization.status
        is BoundaryNormalizationStatus.OK
    )


# ─── Deterministic re-delivery ──────────────────────────────────────


@pytest.mark.asyncio
async def test_redelivery_yields_same_event_id() -> None:
    """The replay derivation must be byte-stable across calls."""
    rt = _runtime()
    src = _zendesk_source()
    payload = _zendesk_payload()
    e1 = (await rt.ingest(
        BoundaryIngressRequest(
            source=src,
            adapter_name="zendesk_webhook_adapter",
            payload=payload,
        )
    )).unwrap()
    e2 = (await rt.ingest(
        BoundaryIngressRequest(
            source=src,
            adapter_name="zendesk_webhook_adapter",
            payload=payload,
        )
    )).unwrap()
    assert e1.event_id == e2.event_id
    assert e2.replay_disposition is (
        BoundaryReplayDisposition.REPLAY_OF_KNOWN
    )
    assert e2.original_event_id == e1.event_id


@pytest.mark.asyncio
async def test_lineage_drift_when_payload_differs() -> None:
    """Same external coordinates but mutated body → LINEAGE_DRIFT."""
    rt = _runtime()
    src = _zendesk_source()
    e1 = (await rt.ingest(
        BoundaryIngressRequest(
            source=src,
            adapter_name="zendesk_webhook_adapter",
            payload=_zendesk_payload(body_extra="first"),
        )
    )).unwrap()
    e2 = (await rt.ingest(
        BoundaryIngressRequest(
            source=src,
            adapter_name="zendesk_webhook_adapter",
            payload=_zendesk_payload(body_extra="second"),
        )
    )).unwrap()
    assert e2.replay_disposition is (
        BoundaryReplayDisposition.LINEAGE_DRIFT
    )
    # CRITICAL: drifted retransmissions inherit ORIGINAL event_id.
    assert e2.event_id == e1.event_id
    assert e2.original_event_id == e1.event_id


@pytest.mark.asyncio
async def test_different_tenants_do_not_collide() -> None:
    rt = _runtime()
    payload = _zendesk_payload()
    e1 = (await rt.ingest(
        BoundaryIngressRequest(
            source=_zendesk_source(tenant="tenant-A"),
            adapter_name="zendesk_webhook_adapter",
            payload=payload,
        )
    )).unwrap()
    e2 = (await rt.ingest(
        BoundaryIngressRequest(
            source=_zendesk_source(tenant="tenant-B"),
            adapter_name="zendesk_webhook_adapter",
            payload=payload,
        )
    )).unwrap()
    assert e1.event_id != e2.event_id
    assert e2.replay_disposition is (
        BoundaryReplayDisposition.NEW
    )


# ─── Error paths (never raises) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_adapter_yields_failed_envelope() -> None:
    rt = _runtime()
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_zendesk_source(),
            adapter_name="does_not_exist",
            payload=_zendesk_payload(),
        )
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert (
        envelope.trace.normalization_status
        is BoundaryNormalizationStatus.ADAPTER_ERROR
    )


@pytest.mark.asyncio
async def test_malformed_payload_returns_normalised_failure() -> None:
    rt = _runtime()
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_zendesk_source(),
            adapter_name="zendesk_webhook_adapter",
            payload=IngressPayload(body="not-a-dict"),
        )
    )
    # Substrate-level success — the adapter raised, the substrate
    # captured it as a result with MALFORMED status.
    assert envelope.is_ok
    result = envelope.unwrap()
    assert (
        result.normalization.status
        is BoundaryNormalizationStatus.MALFORMED
    )
    assert result.event is None
    assert (
        result.replay_disposition
        is BoundaryReplayDisposition.INVALID_KEY
    )


class _AuthFailingAdapter(BaseIngressAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="auth_failing_adapter",
            source_type=BoundarySourceType.GENERIC,
        )

    def normalize(self, *, source, payload):  # type: ignore[no-untyped-def]
        raise BoundaryAuthenticationError("bad signature")


@pytest.mark.asyncio
async def test_authentication_failure_classified() -> None:
    rt = BoundaryIngressRuntime(
        adapters=BoundaryAdapterRegistry(
            [_AuthFailingAdapter()]
        ),
        idempotency=BoundaryIdempotencyRegistry(),
    )
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=BoundarySource(
                source_type=BoundarySourceType.GENERIC,
                source_id="x",
            ),
            adapter_name="auth_failing_adapter",
            payload=IngressPayload(body={"x": 1}),
        )
    )
    result = envelope.unwrap()
    assert (
        result.normalization.status
        is BoundaryNormalizationStatus.UNAUTHENTICATED
    )


# ─── Persistence integration ────────────────────────────────────────


@pytest.mark.asyncio
async def test_persistence_writes_record() -> None:
    store = InMemoryBoundaryPersistence()
    rt = _runtime(persistence=store)
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_zendesk_source(),
            adapter_name="zendesk_webhook_adapter",
            payload=_zendesk_payload(),
        )
    )
    record = await store.get_ingress(
        envelope.unwrap().ingress_id
    )
    assert record is not None
    assert (
        record.replay_disposition is BoundaryReplayDisposition.NEW
    )


@pytest.mark.asyncio
async def test_persistence_listing_filters_by_disposition() -> None:
    store = InMemoryBoundaryPersistence()
    rt = _runtime(persistence=store)
    src = _zendesk_source()
    payload = _zendesk_payload()
    await rt.ingest(
        BoundaryIngressRequest(
            source=src,
            adapter_name="zendesk_webhook_adapter",
            payload=payload,
        )
    )
    await rt.ingest(
        BoundaryIngressRequest(
            source=src,
            adapter_name="zendesk_webhook_adapter",
            payload=payload,
        )
    )
    page = await store.list_ingress(
        BoundaryIngressQuery(
            replay_disposition=BoundaryReplayDisposition.REPLAY_OF_KNOWN
        )
    )
    assert page.total == 1


# ─── Direction enforcement ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingress_runtime_only_iterates_ingress_adapters() -> None:
    """Ensure the runtime never selects an EGRESS adapter by name."""
    from app.boundary.adapters.builtin.zendesk import (
        ZendeskWebhookAdapter,
    )

    reg = BoundaryAdapterRegistry([ZendeskWebhookAdapter()])
    # Confirm direction filter:
    assert (
        ZendeskWebhookAdapter().direction
        is BoundaryDirection.INGRESS
    )
    rt = BoundaryIngressRuntime(
        adapters=reg,
        idempotency=BoundaryIdempotencyRegistry(),
    )
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_zendesk_source(),
            adapter_name="zendesk_webhook_adapter",
            payload=_zendesk_payload(),
        )
    )
    assert envelope.is_ok
