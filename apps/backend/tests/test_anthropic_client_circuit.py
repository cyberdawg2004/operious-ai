"""Anthropic Messages client circuit-breaker integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.cognition.exceptions import CognitionLLMProviderError
from app.cognition.llm import AnthropicMessagesClient, DiagnosticLLMMessage
from app.runtime import (
    ProviderCircuitBreaker,
    ProviderCircuitOpenError,
    ProviderCircuitState,
)

TENANT_ID = "tenant-anthropic-circuit"
NOW = datetime(2026, 5, 23, 13, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_anthropic_client_strips_whitespace_from_header_bound_config() -> None:
    """A trailing newline in ANTHROPIC_API_KEY (a common artifact of how
    secrets get pasted into env vars / CI secret stores) must never reach
    the x-api-key HTTP header — h11 raises LocalProtocolError ("illegal
    header value") for any header value containing \\r or \\n, which a
    real Anthropic call hit in CI the first time a real key was used."""
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(
            200,
            request=request,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AnthropicMessagesClient(
            api_key="secret-test-key\n",
            model="claude-test\n",
            base_url="https://anthropic.test",
            anthropic_version="2023-06-01\n",
            http_client=http,
            default_tenant_id=TENANT_ID,
        )
        completion = await client.complete(
            system_prompt="Return JSON.",
            messages=(DiagnosticLLMMessage(role="user", content="hello"),),
            max_output_tokens=128,
            temperature=0.0,
        )

    assert completion.text == "ok"
    assert captured_headers["x-api-key"] == "secret-test-key"
    assert captured_headers["anthropic-version"] == "2023-06-01"
    assert client.model_name == "claude-test"


@pytest.mark.asyncio
async def test_anthropic_429_transitions_circuit_open() -> None:
    breaker = ProviderCircuitBreaker()
    seen_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_requests
        seen_requests += 1
        return httpx.Response(
            429,
            headers={"retry-after": "17"},
            request=request,
            json={"error": "rate limited"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AnthropicMessagesClient(
            api_key="secret-test-key",
            model="claude-test",
            base_url="https://anthropic.test",
            http_client=http,
            provider_circuit_breaker=breaker,
            default_tenant_id=TENANT_ID,
        )
        with pytest.raises(CognitionLLMProviderError):
            await client.complete(
                system_prompt="Return JSON.",
                messages=(DiagnosticLLMMessage(role="user", content="hello"),),
                max_output_tokens=128,
                temperature=0.0,
            )

    state = await breaker.get_state(
        tenant_id=TENANT_ID,
        provider_name="anthropic",
    )
    assert seen_requests == 1
    assert state.state is ProviderCircuitState.OPEN
    assert state.last_failure_reason == "rate_limit"
    assert state.open_until is not None


@pytest.mark.asyncio
async def test_anthropic_circuit_respects_retry_after_header() -> None:
    breaker = ProviderCircuitBreaker()
    now = datetime.now(timezone.utc)
    await breaker.open(
        tenant_id=TENANT_ID,
        provider_name="anthropic",
        reason="rate_limit",
        open_until=now + timedelta(seconds=30),
        now=now,
    )
    seen_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_requests
        seen_requests += 1
        return httpx.Response(200, request=request, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AnthropicMessagesClient(
            api_key="secret-test-key",
            model="claude-test",
            base_url="https://anthropic.test",
            http_client=http,
            provider_circuit_breaker=breaker,
            default_tenant_id=TENANT_ID,
        )
        with pytest.raises(ProviderCircuitOpenError):
            await client.complete(
                system_prompt="Return JSON.",
                messages=(DiagnosticLLMMessage(role="user", content="hello"),),
                max_output_tokens=128,
                temperature=0.0,
            )

    assert seen_requests == 0


@pytest.mark.asyncio
async def test_anthropic_503_opens_after_three_consecutive_failures() -> None:
    breaker = ProviderCircuitBreaker()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            request=request,
            json={"error": "unavailable"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AnthropicMessagesClient(
            api_key="secret-test-key",
            model="claude-test",
            base_url="https://anthropic.test",
            http_client=http,
            provider_circuit_breaker=breaker,
            default_tenant_id=TENANT_ID,
        )
        for _ in range(3):
            with pytest.raises(CognitionLLMProviderError):
                await client.complete(
                    system_prompt="Return JSON.",
                    messages=(DiagnosticLLMMessage(role="user", content="hello"),),
                    max_output_tokens=128,
                    temperature=0.0,
                )

    state = await breaker.get_state(
        tenant_id=TENANT_ID,
        provider_name="anthropic",
    )
    assert state.state is ProviderCircuitState.OPEN
    assert state.last_failure_reason == "unavailable"
