"""Replay-detector + idempotency-registry behaviour."""

from __future__ import annotations

from typing import TypedDict

import pytest

from app.boundary.enums import (
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    derive_event_id,
    derive_replay_key,
)
from app.boundary.idempotency.detector import (
    BoundaryReplayDetector,
)
from app.boundary.idempotency.registry import (
    BoundaryIdempotencyRegistry,
)


class _BoundaryCoordinates(TypedDict):
    source_type: str
    external_message_id: str
    tenant_id: str | None


def _coords(
    *, msg: str = "evt-1", tenant: str | None = None
) -> _BoundaryCoordinates:
    return {
        "source_type": "zendesk",
        "external_message_id": msg,
        "tenant_id": tenant,
    }


@pytest.mark.asyncio
async def test_first_classification_is_new() -> None:
    detector = BoundaryReplayDetector()
    registry = BoundaryIdempotencyRegistry()
    decision = await detector.classify(
        replay_key=derive_replay_key(**_coords()),
        content_fingerprint="abc",
        registry=registry,
    )
    assert decision.disposition is BoundaryReplayDisposition.NEW
    assert decision.original_event_id is None


@pytest.mark.asyncio
async def test_replay_of_known_when_fingerprint_matches() -> None:
    detector = BoundaryReplayDetector()
    registry = BoundaryIdempotencyRegistry()
    coords = _coords()
    replay_key = derive_replay_key(**coords)
    event_id = derive_event_id(**coords)
    await registry.record_first_seen(
        replay_key=replay_key,
        event_id=event_id,
        source_type=BoundarySourceType.ZENDESK,
        external_message_id="evt-1",
        tenant_id=None,
        content_fingerprint="abc",
    )
    decision = await detector.classify(
        replay_key=replay_key,
        content_fingerprint="abc",
        registry=registry,
    )
    assert (
        decision.disposition
        is BoundaryReplayDisposition.REPLAY_OF_KNOWN
    )
    assert decision.original_event_id == event_id


@pytest.mark.asyncio
async def test_lineage_drift_when_fingerprint_differs() -> None:
    detector = BoundaryReplayDetector()
    registry = BoundaryIdempotencyRegistry()
    coords = _coords()
    replay_key = derive_replay_key(**coords)
    event_id = derive_event_id(**coords)
    await registry.record_first_seen(
        replay_key=replay_key,
        event_id=event_id,
        source_type=BoundarySourceType.ZENDESK,
        external_message_id="evt-1",
        tenant_id=None,
        content_fingerprint="original-fingerprint",
    )
    decision = await detector.classify(
        replay_key=replay_key,
        content_fingerprint="different-fingerprint",
        registry=registry,
    )
    assert (
        decision.disposition
        is BoundaryReplayDisposition.LINEAGE_DRIFT
    )
    assert decision.original_event_id == event_id


@pytest.mark.asyncio
async def test_invalid_key_when_replay_key_is_none() -> None:
    detector = BoundaryReplayDetector()
    registry = BoundaryIdempotencyRegistry()
    decision = await detector.classify(
        replay_key=None,
        content_fingerprint="abc",
        registry=registry,
    )
    assert (
        decision.disposition
        is BoundaryReplayDisposition.INVALID_KEY
    )


@pytest.mark.asyncio
async def test_record_first_seen_rejects_duplicate_keys() -> None:
    registry = BoundaryIdempotencyRegistry()
    coords = _coords()
    replay_key = derive_replay_key(**coords)
    event_id = derive_event_id(**coords)
    await registry.record_first_seen(
        replay_key=replay_key,
        event_id=event_id,
        source_type=BoundarySourceType.ZENDESK,
        external_message_id="evt-1",
        tenant_id=None,
        content_fingerprint="abc",
    )
    with pytest.raises(ValueError):
        await registry.record_first_seen(
            replay_key=replay_key,
            event_id=event_id,
            source_type=BoundarySourceType.ZENDESK,
            external_message_id="evt-1",
            tenant_id=None,
            content_fingerprint="abc",
        )


@pytest.mark.asyncio
async def test_record_observation_preserves_original_lineage() -> None:
    """The substrate NEVER mutates the first event_id / first_seen_at."""
    registry = BoundaryIdempotencyRegistry()
    coords = _coords()
    replay_key = derive_replay_key(**coords)
    event_id = derive_event_id(**coords)
    original = await registry.record_first_seen(
        replay_key=replay_key,
        event_id=event_id,
        source_type=BoundarySourceType.ZENDESK,
        external_message_id="evt-1",
        tenant_id=None,
        content_fingerprint="fp",
    )
    updated = await registry.record_observation(
        replay_key=replay_key,
        disposition=BoundaryReplayDisposition.REPLAY_OF_KNOWN,
        observed_fingerprint="fp",
    )
    assert updated.event_id == original.event_id
    assert updated.first_seen_at == original.first_seen_at
    assert updated.observation_count == 2
    assert (
        updated.last_disposition
        is BoundaryReplayDisposition.REPLAY_OF_KNOWN
    )


@pytest.mark.asyncio
async def test_record_observation_rejects_unknown_keys() -> None:
    registry = BoundaryIdempotencyRegistry()
    with pytest.raises(KeyError):
        await registry.record_observation(
            replay_key=derive_replay_key(**_coords()),
            disposition=BoundaryReplayDisposition.REPLAY_OF_KNOWN,
            observed_fingerprint="x",
        )
