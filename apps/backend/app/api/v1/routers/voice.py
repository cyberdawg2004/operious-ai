"""Voice media WebSocket gateway."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, WebSocket, WebSocketException, status
from starlette.websockets import WebSocketDisconnect

from app.boundary.voice.adapters.twilio import TwilioMediaStreamAdapter
from app.boundary.voice.call import (
    VoiceCallSessionRuntime,
    VoiceCapacityCounter,
)

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
    tenant_id = websocket.query_params.get("tenant")
    if not tenant_id:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

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
) -> None:
    try:
        while True:
            raw = await websocket.receive_text()
            event = adapter.parse_message(raw)
            if event.event in {"connected", "start"}:
                continue
            if event.event == "media":
                audio = adapter.audio_handle_from_media(
                    event=event,
                    session_id=session_id,
                    tenant_id=tenant_id,
                )
                await runtime.handle_audio_chunk(
                    call_id=call_id,
                    audio_handle=audio,
                    expected_tenant_id=tenant_id,
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
