"""Phase F request-body limit middleware tests."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.middleware.request_body_limit import RequestBodyLimitMiddleware

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


@pytest.mark.asyncio
async def test_request_body_exceeding_limit_returns_413() -> None:
    receive_called = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal receive_called
        receive_called = True
        await _ok(send)

    middleware = RequestBodyLimitMiddleware(app, max_bytes=4)
    sent = await _run_asgi(
        middleware,
        scope=_scope(headers=[(b"content-length", b"5")]),
        messages=(),
    )

    assert not receive_called
    assert sent[0]["status"] == 413
    assert sent[1]["body"] == b'{"detail":{"code":"request_body_too_large"}}'


@pytest.mark.asyncio
async def test_chunked_request_body_limit_enforced_incrementally() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = bool(message.get("more_body", False))
        await _ok(send, body=body)

    middleware = RequestBodyLimitMiddleware(app, max_bytes=5)
    sent = await _run_asgi(
        middleware,
        scope=_scope(headers=[]),
        messages=(
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ),
    )

    assert sent[0]["status"] == 413
    assert sent[1]["body"] == b'{"detail":{"code":"request_body_too_large"}}'


def test_request_body_limit_middleware_registered_outermost() -> None:
    main_path = APP_ROOT / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    registered: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "add_middleware"
            and node.args
        ):
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Name):
            registered.append((node.lineno, first_arg.id))

    assert sorted(registered)[-1][1] == "RequestBodyLimitMiddleware"


async def _run_asgi(
    app: Any,
    *,
    scope: Scope,
    messages: tuple[Message, ...],
) -> list[Message]:
    sent: list[Message] = []
    queue = list(messages)

    async def receive() -> Message:
        if queue:
            return queue.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _scope(
    *,
    headers: list[tuple[bytes, bytes]],
) -> Scope:
    return {
        "type": "http",
        "method": "POST",
        "path": "/webhook",
        "raw_path": b"/webhook",
        "query_string": b"",
        "headers": headers,
        "http_version": "1.1",
        "scheme": "http",
        "client": ("127.0.0.1", 10000),
        "server": ("testserver", 80),
    }


async def _ok(send: Send, *, body: bytes = b"ok") -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", str(len(body)).encode("ascii"))],
        }
    )
    await send({"type": "http.response.body", "body": body})
