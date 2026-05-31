"""Voice media WebSocket gateway."""

from __future__ import annotations

import time
from typing import cast

from fastapi import APIRouter, Depends, WebSocket, WebSocketException, status
from starlette.websockets import WebSocketDisconnect

from app.boundary.voice.adapters.twilio import TwilioMediaStreamAdapter
from app.boundary.voice.call import (
    VoiceCallSessionRuntime,
    VoiceCapacityCounter,
)
from app.boundary.voice.session_token import (
    VoiceSessionTokenError,
    verify_voice_session_token,
)
from app.core.config import get_settings

router = APIRouter(tags=["voice"])


def get_voice_capacity_counter(
    websocket: WebSocket,
) -> VoiceCapacityCounter:
    return cast(
        VoiceCapacityCounter,
        websocket.app.state.voice_capacity_counter,
    )


@router.websocket("/{session_id}/stream")
async def stream_voice_session(
    websocket: WebSocket,
    session_id: str,
    capacity: VoiceCapacityCounter = Depends(get_voice_capacity_counter),
) -> None:
    settings = get_settings()

    # 1. Voice must be explicitly enabled (S-04, fail-closed default).
    if not settings.VOICE_ENABLED:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    # 2. Tenant identity comes from a verified signed session token, NOT
    #    from a spoofable ``?tenant=`` query parameter. The token binds
    #    tenant + session + expiry; verification happens before accept().
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    try:
        tenant_id = verify_voice_session_token(
            secret=settings.VOICE_SESSION_TOKEN_SECRET,
            token=token,
            session_id=session_id,
            now=int(time.time()),
        )
    except VoiceSessionTokenError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION) from None

    if not await capacity.is_available():
        raise WebSocketException(code=status.WS_1013_TRY_AGAIN_LATER)
    acquired = await capacity.try_acquire()
    if not acquired:
        raise WebSocketException(code=status.WS_1013_TRY_AGAIN_LATER)

    runtime = websocket.app.state.voice_call_runtime
    if not isinstance(runtime, VoiceCallSessionRuntime):
        await capacity.release()
        raise WebSocketException(code=status.WS_1011_INTERNAL_ERROR)

    await websocket.accept()
    adapter = TwilioMediaStreamAdapter()
    call_id: str | None = None
    try:
        context = await runtime.start_call(
            session_id=session_id,
            tenant_id=tenant_id,
            call_nonce=session_id,
        )
        call_id = context.call_id
        await _handle_voice_call(
            websocket=websocket,
            adapter=adapter,
            runtime=runtime,
            call_id=call_id,
            session_id=session_id,
            tenant_id=tenant_id,
            max_frame_bytes=settings.VOICE_MAX_FRAME_BYTES,
            max_frames=settings.VOICE_MAX_FRAMES_PER_CALL,
        )
    finally:
        try:
            if call_id is not None and runtime.get_context(call_id) is not None:
                await runtime.terminate_call(
                    call_id=call_id,
                    reason="websocket_handler_exit",
                    expected_tenant_id=tenant_id,
                )
        finally:
            await capacity.release()


async def _handle_voice_call(
    *,
    websocket: WebSocket,
    adapter: TwilioMediaStreamAdapter,
    runtime: VoiceCallSessionRuntime,
    call_id: str,
    session_id: str,
    tenant_id: str,
    max_frame_bytes: int,
    max_frames: int,
) -> None:
    frames_seen = 0
    try:
        while True:
            raw = await websocket.receive_text()
            # Bound per-frame size and per-call frame count (S-04 DoS).
            if len(raw.encode("utf-8")) > max_frame_bytes:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                await runtime.terminate_call(
                    call_id=call_id,
                    reason="voice_frame_too_large",
                    expected_tenant_id=tenant_id,
                )
                return
            frames_seen += 1
            if frames_seen > max_frames:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                await runtime.terminate_call(
                    call_id=call_id,
                    reason="voice_frame_limit_exceeded",
                    expected_tenant_id=tenant_id,
                )
                return
            event = adapter.parse_message(raw)
            if event.event in {"connected", "start"}:
                continue
            if event.event == "media":
                audio = adapter.audio_handle_from_media(
                    event=event,
                    session_id=session_id,
                    tenant_id=tenant_id,
                )
                context = await runtime.handle_audio_chunk(
                    call_id=call_id,
                    audio_handle=audio,
                    expected_tenant_id=tenant_id,
                )
                await websocket.send_json(
                    {
                        "event": "phase_a_ack",
                        "call_id": call_id,
                        "state": context.state.value,
                        "turn_count": context.turn_count,
                    }
                )
                continue
            if event.event == "stop":
                await runtime.terminate_call(
                    call_id=call_id,
                    reason="twilio_stop",
                    expected_tenant_id=tenant_id,
                )
                await websocket.close()
                return
    except WebSocketDisconnect:
        context = runtime.get_context(call_id)
        if context is None:
            return
        await runtime.terminate_call(
            call_id=call_id,
            reason="websocket_disconnect",
            expected_tenant_id=tenant_id,
        )


__all__ = ["router", "get_voice_capacity_counter"]
