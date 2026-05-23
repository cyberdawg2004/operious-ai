"""ASGI request-body limit enforcement."""

from __future__ import annotations

from typing import cast

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

_JSON_RESPONSE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-type", b"application/json"),
)
_REQUEST_TOO_LARGE_BODY = b'{"detail":{"code":"request_body_too_large"}}'


class RequestBodyLimitMiddleware:
    """Reject HTTP request bodies above the configured byte ceiling."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = (
            max_bytes
            if max_bytes is not None
            else get_settings().SURVIVABILITY_REQUEST_BODY_MAX_BYTES
        )
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await _send_request_too_large(send)
            return

        seen = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if isinstance(body, bytes):
                    seen += len(body)
                if seen > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await _send_request_too_large(send)


class _RequestBodyTooLarge(Exception):
    """Internal control-flow marker for incremental body enforcement."""


def _content_length(scope: Scope) -> int | None:
    headers = cast(
        list[tuple[bytes, bytes]],
        scope.get("headers", []),
    )
    for raw_name, raw_value in headers:
        if raw_name.lower() != b"content-length":
            continue
        try:
            return int(raw_value.decode("latin-1").strip())
        except ValueError:
            return None
    return None


async def _send_request_too_large(send: Send) -> None:
    headers = (
        *_JSON_RESPONSE_HEADERS,
        (b"content-length", str(len(_REQUEST_TOO_LARGE_BODY)).encode("ascii")),
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": _REQUEST_TOO_LARGE_BODY,
        }
    )


__all__ = ["RequestBodyLimitMiddleware"]
