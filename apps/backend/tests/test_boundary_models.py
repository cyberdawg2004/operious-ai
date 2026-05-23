"""Frozen-shape + replay-safety invariants for boundary models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import TypedDict

import pytest

from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    derive_event_id,
    derive_replay_key,
)
from app.boundary.models.event import ExternalBoundaryEvent
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.payload import (
    EgressPayload,
    IngressPayload,
)
from app.boundary.models.replay import BoundaryReplayRecord
from app.boundary.models.source import BoundarySource


class _BoundaryCoordinates(TypedDict):
    source_type: str
    external_message_id: str
    tenant_id: str | None


def _source() -> BoundarySource:
    return BoundarySource(
        source_type=BoundarySourceType.ZENDESK,
        source_id="acct-1",
        tenant_id="tenant-1",
    )


def test_boundary_source_rejects_empty_source_id() -> None:
    with pytest.raises(ValueError):
        BoundarySource(
            source_type=BoundarySourceType.ZENDESK,
            source_id="",
        )


def test_boundary_source_is_frozen() -> None:
    src = _source()
    with pytest.raises(FrozenInstanceError):
        src.source_id = "mut"  # type: ignore[misc]


def test_external_boundary_event_is_frozen_and_slotted() -> None:
    event_id = derive_event_id(
        source_type="zendesk", external_message_id="x"
    )
    event = ExternalBoundaryEvent(
        event_id=event_id,
        source=_source(),
        message_type=BoundaryMessageType.EVENT_CREATED,
        external_message_id="x",  # type: ignore[arg-type]
        canonical_payload={"a": 1},
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        event.received_at = datetime.now(tz=timezone.utc)  # type: ignore[misc]


def test_boundary_replay_record_is_frozen() -> None:
    coords: _BoundaryCoordinates = {
        "source_type": "zendesk",
        "external_message_id": "x",
        "tenant_id": None,
    }
    record = BoundaryReplayRecord(
        replay_key=derive_replay_key(**coords),
        event_id=derive_event_id(**coords),
        source_type=BoundarySourceType.ZENDESK,
        external_message_id="x",
        tenant_id=None,
        content_fingerprint="abc",
        first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_disposition=BoundaryReplayDisposition.NEW,
    )
    with pytest.raises(FrozenInstanceError):
        record.observation_count = 99  # type: ignore[misc]


def test_payloads_are_frozen() -> None:
    ip = IngressPayload(body={"x": 1})
    op = EgressPayload(body={"y": 1})
    with pytest.raises(FrozenInstanceError):
        ip.body = "mut"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        op.body = "mut"  # type: ignore[misc]


def test_normalization_result_is_ok_helper() -> None:
    ok = BoundaryNormalizationResult(
        status=BoundaryNormalizationStatus.OK
    )
    bad = BoundaryNormalizationResult(
        status=BoundaryNormalizationStatus.MALFORMED
    )
    assert ok.is_ok
    assert not bad.is_ok


def test_models_have_slots_attribute() -> None:
    # __slots__ implies no __dict__ on instances
    src = _source()
    with pytest.raises(AttributeError):
        src.__dict__  # noqa: B018
