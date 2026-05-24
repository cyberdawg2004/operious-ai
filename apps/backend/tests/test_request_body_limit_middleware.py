"""Phase F request-body limit middleware tests."""

from __future__ import annotations

import ast
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

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
    assert _json_body(sent)["title"] == "request_body_too_large"
    assert _json_body(sent)["status"] == 413
    assert _json_body(sent)["max_bytes"] == 4
    assert (
        _header(sent[0], b"content-type") == b"application/problem+json"
    )


@pytest.mark.asyncio
async def test_chunked_request_body_limit_enforced_incrementally() -> None:
    receive_calls = 0

    def increment_receive_calls() -> None:
        nonlocal receive_calls
        receive_calls += 1

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
            {"type": "http.request", "body": b"ghi", "more_body": False},
        ),
        on_receive=increment_receive_calls,
    )

    assert sent[0]["status"] == 413
    assert _json_body(sent)["code"] == "request_body_too_large"
    assert _json_body(sent)["max_bytes"] == 5
    assert receive_calls == 2


@pytest.mark.asyncio
async def test_request_body_under_limit_passes_through_normally() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        message = await receive()
        await _ok(send, body=message.get("body", b""))

    middleware = RequestBodyLimitMiddleware(app, max_bytes=6)
    sent = await _run_asgi(
        middleware,
        scope=_scope(headers=[(b"content-length", b"6")]),
        messages=(
            {"type": "http.request", "body": b"abcdef", "more_body": False},
        ),
    )

    assert sent[0]["status"] == 200
    assert sent[1]["body"] == b"abcdef"


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


def test_create_app_user_middleware_has_body_limit_outermost() -> None:
    from app.main import create_app

    app = create_app()

    assert app.user_middleware[0].cls is RequestBodyLimitMiddleware


def test_request_body_limit_middleware_does_not_call_request_body() -> None:
    middleware_path = APP_ROOT / "middleware" / "request_body_limit.py"
    tree = ast.parse(middleware_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        assert node.attr != "body"


def test_create_app_sources_body_limit_from_settings() -> None:
    main_path = APP_ROOT / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_middleware"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "RequestBodyLimitMiddleware"
        ):
            continue
        for keyword in node.keywords:
            value = keyword.value
            if (
                keyword.arg == "max_bytes"
                and isinstance(value, ast.Attribute)
                and value.attr == "SURVIVABILITY_REQUEST_BODY_MAX_BYTES"
            ):
                found = True
    assert found


async def _run_asgi(
    app: Any,
    *,
    scope: Scope,
    messages: tuple[Message, ...],
    on_receive: Any | None = None,
) -> list[Message]:
    sent: list[Message] = []
    queue = list(messages)

    async def receive() -> Message:
        if on_receive is not None:
            on_receive()
        if queue:
            return queue.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _json_body(messages: list[Message]) -> dict[str, Any]:
    return json.loads(messages[1]["body"])


def _header(message: Message, name: bytes) -> bytes | None:
    headers = message.get("headers", [])
    if not isinstance(headers, list | tuple):
        return None
    raw_headers = cast(Iterable[tuple[bytes, bytes]], headers)
    for raw_name, raw_value in raw_headers:
        if raw_name.lower() == name:
            return raw_value
    return None


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
