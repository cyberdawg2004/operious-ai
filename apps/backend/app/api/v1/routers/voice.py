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
from app.core.twilio_signature import (
    TWILIO_CANONICAL_URL_HEADER,
    TWILIO_SIGNATURE_HEADER,
    verify_twilio_signature,
)
from app.core.webhook_url import (
    CanonicalWebhookUrlError,
    derive_canonical_webhook_url,
)
from app.services.voice_provider_auth import (
    VoiceProviderAuthTokenLoader,
    get_voice_provider_auth_token_loader,
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

    auth_token_loader = _voice_provider_auth_token_loader(websocket)
    try:
        provider_auth_token = await auth_token_loader(tenant_id)
    except Exception:  # noqa: BLE001 - provider auth lookup fails closed.
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION) from None
    if not provider_auth_token or not _verify_voice_provider_signature(
        websocket=websocket,
        auth_token=provider_auth_token,
        public_base_url=settings.public_base_url_normalized,
        trust_url_header=settings.WEBHOOK_TRUST_URL_HEADER,
    ):
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


def _voice_provider_auth_token_loader(
    websocket: WebSocket,
) -> VoiceProviderAuthTokenLoader:
    configured = getattr(websocket.app.state, "voice_provider_auth_token_loader", None)
    if configured is not None:
        return cast(VoiceProviderAuthTokenLoader, configured)
    return get_voice_provider_auth_token_loader()


def _verify_voice_provider_signature(
    *,
    websocket: WebSocket,
    auth_token: str,
    public_base_url: str,
    trust_url_header: bool,
) -> bool:
    url = _voice_canonical_url(
        websocket=websocket,
        public_base_url=public_base_url,
        trust_url_header=trust_url_header,
    )
    if url is None:
        return False
    return verify_twilio_signature(
        auth_token=auth_token,
        url=url,
        params=None,
        signature=websocket.headers.get(TWILIO_SIGNATURE_HEADER),
    )


def _voice_canonical_url(
    *,
    websocket: WebSocket,
    public_base_url: str,
    trust_url_header: bool,
) -> str | None:
    """The URL the voice provider signature is verified against (#23).

    Derived server-side from ``PUBLIC_BASE_URL`` + the WebSocket path, never a
    client-supplied header unless ``WEBHOOK_TRUST_URL_HEADER`` is set (non-prod).
    """
    if trust_url_header:
        return websocket.headers.get(TWILIO_CANONICAL_URL_HEADER)
    path = websocket.scope.get("path", "")
    raw_query = websocket.scope.get("query_string", b"")
    query = raw_query.decode("latin-1") if isinstance(raw_query, bytes) else str(raw_query)
    try:
        return derive_canonical_webhook_url(
            public_base_url=public_base_url,
            request_path=path,
            query_string=query,
        )
    except CanonicalWebhookUrlError:
        return None


__all__ = [
    "get_voice_capacity_counter",
    "get_voice_provider_auth_token_loader",
    "router",
]
