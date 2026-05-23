"""Phase 6-D.2 shared outbound HTTP client tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.cognition.llm import AnthropicMessagesClient, DiagnosticLLMMessage
from app.core.http import (
    close_shared_http_client,
    get_shared_http_client,
    init_shared_http_client,
)

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


@pytest.mark.asyncio
async def test_shared_http_client_lifecycle_reuses_and_closes_pool() -> None:
    await close_shared_http_client()

    first = init_shared_http_client()
    second = get_shared_http_client()

    assert first is second
    assert not first.is_closed

    await close_shared_http_client()

    assert first.is_closed
    third = get_shared_http_client()
    assert third is not first

    await close_shared_http_client()


@pytest.mark.asyncio
async def test_anthropic_client_uses_injected_shared_client() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg-test",
                "model": "claude-test",
                "role": "assistant",
                "type": "message",
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '{"summary":"ok","category":"account",'
                            '"confidence":0.91,'
                            '"reasoning":"Account category supplied by test."}'
                        ),
                    }
                ],
                "usage": {"input_tokens": 7, "output_tokens": 11},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as shared_client:
        client = AnthropicMessagesClient(
            api_key="secret-test-key",
            model="claude-test",
            base_url="https://anthropic.test",
            http_client=shared_client,
        )

        completion = await client.complete(
            system_prompt="Return JSON.",
            messages=(DiagnosticLLMMessage(role="user", content="hello"),),
            max_output_tokens=128,
            temperature=0.0,
        )

    assert len(seen_requests) == 1
    assert str(seen_requests[0].url) == "https://anthropic.test/v1/messages"
    assert seen_requests[0].headers["x-api-key"] == "secret-test-key"
    assert completion.text == (
        '{"summary":"ok","category":"account","confidence":0.91,'
        '"reasoning":"Account category supplied by test."}'
    )
    assert completion.usage.prompt_tokens == 7
    assert completion.usage.completion_tokens == 11
    assert completion.usage.total_tokens == 18


def test_app_code_only_constructs_outbound_async_client_in_core_http() -> None:
    offenders: list[str] = []
    allowed = Path("core/http.py")
    for path in APP_ROOT.rglob("*.py"):
        relative = path.relative_to(APP_ROOT)
        if relative.parts and relative.parts[0] == "_deprecated":
            continue
        text = path.read_text(encoding="utf-8")
        if "httpx.AsyncClient(" in text and relative != allowed:
            offenders.append(str(relative))

    assert not offenders
