"""Stub Twilio Media Streams adapter."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, cast

from app.boundary.voice.enums import AudioFormat
from app.boundary.voice.models.audio import VoiceAudioHandle


@dataclass(frozen=True, slots=True)
class TwilioMediaStreamEvent:
    event: str
    stream_sid: str | None
    payload: str | None
    sequence_number: str | None
    raw: Mapping[str, Any]


class TwilioMediaStreamAdapter:
    """Translate Twilio Media Streams JSON to voice handles."""

    def parse_message(
        self, message: str | bytes | Mapping[str, Any]
    ) -> TwilioMediaStreamEvent:
        if isinstance(message, bytes):
            data = cast(
                dict[str, Any], json.loads(message.decode("utf-8"))
            )
        elif isinstance(message, str):
            data = cast(dict[str, Any], json.loads(message))
        else:
            data = dict(message)
        media = cast(object, data.get("media"))
        payload_object: object | None = None
        if isinstance(media, Mapping):
            payload_object = cast(Mapping[str, object], media).get(
                "payload"
            )
        payload = (
            str(payload_object) if payload_object is not None else None
        )
        return TwilioMediaStreamEvent(
            event=str(data.get("event") or ""),
            stream_sid=(
                str(data.get("streamSid"))
                if data.get("streamSid") is not None
                else None
            ),
            payload=payload,
            sequence_number=(
                str(data.get("sequenceNumber"))
                if data.get("sequenceNumber") is not None
                else None
            ),
            raw=data,
        )

    def audio_handle_from_media(
        self,
        *,
        event: TwilioMediaStreamEvent,
        session_id: str,
        tenant_id: str,
    ) -> VoiceAudioHandle:
        payload = event.payload or ""
        audio_id = uuid.uuid5(uuid.NAMESPACE_URL, f"twilio|{payload}")
        return VoiceAudioHandle(
            handle=f"twilio-media:{audio_id}",
            audio_format=AudioFormat.G711_MULAW,
            sample_rate_hz=8000,
            duration_ms=20,
            language="en",
            attributes={
                "audio_handle_id": str(audio_id),
                "base64_payload": payload,
                "provider_kind": "twilio_stub",
                "session_id": session_id,
                "tenant_id": tenant_id,
                "stream_sid": event.stream_sid,
                "sequence_number": event.sequence_number,
            },
        )

    def format_media_event(
        self, audio: VoiceAudioHandle
    ) -> dict[str, object]:
        payload = base64.b64encode(
            audio.handle.encode("utf-8")
        ).decode("ascii")
        return {"event": "media", "media": {"payload": payload}}

    def format_mark_event(self, name: str) -> dict[str, object]:
        return {"event": "mark", "mark": {"name": name}}

    def format_clear_event(self) -> dict[str, object]:
        return {"event": "clear"}


__all__ = [
    "TwilioMediaStreamAdapter",
    "TwilioMediaStreamEvent",
]
