"""Voice media WebSocket gateway."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketException, status
from starlette.websockets import WebSocketDisconnect

from app.boundary.voice.adapters.twilio import TwilioMediaStreamAdapter
from app.boundary.voice.call import VoiceCallSessionRuntime

router = APIRouter(tags=["voice"])


@router.websocket("/{session_id}/stream")
async def stream_voice_session(
    websocket: WebSocket,
    session_id: str,
) -> None:
    tenant_id = websocket.query_params.get("tenant")
    if not tenant_id:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    await websocket.accept()
    adapter = TwilioMediaStreamAdapter()
    runtime = websocket.app.state.voice_call_runtime
    if not isinstance(runtime, VoiceCallSessionRuntime):
        await websocket.close(code=1011)
        return

    context = await runtime.start_call(
        session_id=session_id,
        tenant_id=tenant_id,
        call_nonce=session_id,
    )
    call_id = context.call_id
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
        await runtime.terminate_call(
            call_id=call_id,
            reason="websocket_disconnect",
            expected_tenant_id=tenant_id,
        )


__all__ = ["router"]
