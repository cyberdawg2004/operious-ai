"""Spec 1b — voice WebSocket frame-rate cap primitive (#40)."""

from __future__ import annotations

import json
from collections.abc import Iterable

import pytest
from fastapi import status

from app.api.v1.routers.voice import (
    FrameRateExceeded,
    _enforce_frame_rate,
    _handle_voice_call,
)
from app.boundary.voice.adapters.twilio import TwilioMediaStreamAdapter


def test_frame_rate_cap_trips_over_limit() -> None:
    window: list[float] = []
    _enforce_frame_rate(window, now=100.0, max_per_second=2)
    _enforce_frame_rate(window, now=100.1, max_per_second=2)
    with pytest.raises(FrameRateExceeded):
        _enforce_frame_rate(window, now=100.2, max_per_second=2)


def test_frame_rate_window_evicts_old_timestamps() -> None:
    window: list[float] = []
    _enforce_frame_rate(window, now=100.0, max_per_second=2)
    _enforce_frame_rate(window, now=100.4, max_per_second=2)
    # 1.1s after the first frame: both prior timestamps fall out of the window.
    _enforce_frame_rate(window, now=101.5, max_per_second=2)
    assert len(window) == 1


def test_frame_rate_allows_steady_under_limit() -> None:
    window: list[float] = []
    # 1 frame per second, cap 2/sec — never trips.
    for i in range(10):
        _enforce_frame_rate(window, now=float(i), max_per_second=2)
    assert len(window) <= 2


@pytest.mark.asyncio
async def test_over_rate_stream_is_closed_and_call_terminated() -> None:
    runtime = _RuntimeProbe()
    websocket = _QueuedWebSocket(
        [
            {"event": "start"},
            {"event": "start"},
            {"event": "start"},
            {"event": "stop"},
        ]
    )

    await _handle_voice_call(
        websocket=websocket,  # type: ignore[arg-type]
        adapter=TwilioMediaStreamAdapter(),
        runtime=runtime,  # type: ignore[arg-type]
        call_id="call-over-rate",
        session_id="session-over-rate",
        tenant_id="tenant-over-rate",
        max_frame_bytes=4096,
        max_frames=10,
        max_call_seconds=60,
        idle_timeout_seconds=5,
        max_frames_per_second=2,
    )

    assert websocket.close_codes == [status.WS_1008_POLICY_VIOLATION]
    assert runtime.terminations == [("call-over-rate", "voice_frame_rate_exceeded")]


class _QueuedWebSocket:
    def __init__(self, messages: Iterable[dict[str, object]]) -> None:
        self._messages = [json.dumps(message) for message in messages]
        self.close_codes: list[int] = []

    async def receive_text(self) -> str:
        return self._messages.pop(0)

    async def close(self, code: int = status.WS_1000_NORMAL_CLOSURE) -> None:
        self.close_codes.append(code)

    async def send_json(self, data: object) -> None:
        del data


class _RuntimeProbe:
    def __init__(self) -> None:
        self.terminations: list[tuple[str, str]] = []

    async def terminate_call(
        self,
        *,
        call_id: str,
        reason: str,
        expected_tenant_id: str,
    ) -> None:
        del expected_tenant_id
        self.terminations.append((call_id, reason))
