"""Wire-format pinning for boundary substrate enums."""

from __future__ import annotations

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)


_DIRECTION_WIRE: dict[BoundaryDirection, str] = {
    BoundaryDirection.INGRESS: "ingress",
    BoundaryDirection.EGRESS: "egress",
}


_SOURCE_TYPE_WIRE: dict[BoundarySourceType, str] = {
    BoundarySourceType.ZENDESK: "zendesk",
    BoundarySourceType.WHATSAPP: "whatsapp",
    BoundarySourceType.TWILIO_VOICE: "twilio_voice",
    BoundarySourceType.TWILIO_SMS: "twilio_sms",
    BoundarySourceType.EMAIL: "email",
    BoundarySourceType.SHULEX: "shulex",
    BoundarySourceType.LARK: "lark",
    BoundarySourceType.SLACK: "slack",
    BoundarySourceType.REST_API: "rest_api",
    BoundarySourceType.GENERIC: "generic",
}


_MESSAGE_TYPE_WIRE: dict[BoundaryMessageType, str] = {
    BoundaryMessageType.MESSAGE_RECEIVED: "message_received",
    BoundaryMessageType.MESSAGE_DELIVERED: "message_delivered",
    BoundaryMessageType.STATUS_UPDATE: "status_update",
    BoundaryMessageType.EVENT_CREATED: "event_created",
    BoundaryMessageType.EVENT_UPDATED: "event_updated",
    BoundaryMessageType.STREAM_FRAME: "stream_frame",
    BoundaryMessageType.PRESENCE_UPDATE: "presence_update",
    BoundaryMessageType.UNKNOWN: "unknown",
}


_NORMALIZATION_STATUS_WIRE: dict[
    BoundaryNormalizationStatus, str
] = {
    BoundaryNormalizationStatus.OK: "ok",
    BoundaryNormalizationStatus.MALFORMED: "malformed",
    BoundaryNormalizationStatus.UNAUTHENTICATED: "unauthenticated",
    BoundaryNormalizationStatus.UNSUPPORTED_TYPE: "unsupported_type",
    BoundaryNormalizationStatus.ADAPTER_ERROR: "adapter_error",
}


_REPLAY_DISPOSITION_WIRE: dict[
    BoundaryReplayDisposition, str
] = {
    BoundaryReplayDisposition.NEW: "new",
    BoundaryReplayDisposition.REPLAY_OF_KNOWN: "replay_of_known",
    BoundaryReplayDisposition.LINEAGE_DRIFT: "lineage_drift",
    BoundaryReplayDisposition.INVALID_KEY: "invalid_key",
}


def test_direction_wire_pinned() -> None:
    for member, expected in _DIRECTION_WIRE.items():
        assert member.value == expected
    assert set(BoundaryDirection) == set(_DIRECTION_WIRE.keys())


def test_source_type_wire_pinned() -> None:
    for member, expected in _SOURCE_TYPE_WIRE.items():
        assert member.value == expected
    assert set(BoundarySourceType) == set(_SOURCE_TYPE_WIRE.keys())


def test_message_type_wire_pinned() -> None:
    for member, expected in _MESSAGE_TYPE_WIRE.items():
        assert member.value == expected
    assert set(BoundaryMessageType) == set(_MESSAGE_TYPE_WIRE.keys())


def test_normalization_status_wire_pinned() -> None:
    for member, expected in _NORMALIZATION_STATUS_WIRE.items():
        assert member.value == expected
    assert set(BoundaryNormalizationStatus) == set(
        _NORMALIZATION_STATUS_WIRE.keys()
    )


def test_replay_disposition_wire_pinned() -> None:
    for member, expected in _REPLAY_DISPOSITION_WIRE.items():
        assert member.value == expected
    assert set(BoundaryReplayDisposition) == set(
        _REPLAY_DISPOSITION_WIRE.keys()
    )
