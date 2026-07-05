"""Bedrock LLM client and factory tests.

Tests verify:
- BedrockAnthropicMessagesClient satisfies DiagnosticLLMClient protocol
- build_llm_client returns Bedrock client when LLM_PROVIDER=bedrock
- build_llm_client returns Anthropic client when LLM_PROVIDER=anthropic
- build_llm_client returns Deterministic when no creds configured outside production
- build_llm_client fails closed when production creds/config are missing
- Bedrock request/response translation is correct (boto3 mocked)
- Bedrock error codes map to correct exception types
- prefer_reasoning_model flag selects the right model
- No anthropic SDK import in llm_bedrock.py (vendor isolation)
- Configuration validation: empty region raises CognitionLLMConfigurationError
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.cognition.exceptions import (
    CognitionLLMConfigurationError,
    CognitionLLMProviderError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from app.cognition.llm import DiagnosticLLMClient, DiagnosticLLMMessage
from app.cognition.llm_bedrock import BedrockAnthropicMessagesClient
from app.cognition.llm_factory import build_llm_client
from app.cognition.models import DiagnosticLLMCompletion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_bedrock_response(
    text: str = "Test response",
    input_tokens: int = 10,
    output_tokens: int = 5,
    stop_reason: str = "end_turn",
) -> dict[str, Any]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            }
        },
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
        },
        "stopReason": stop_reason,
    }


def _make_client(
    model: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    region: str = "us-east-1",
) -> BedrockAnthropicMessagesClient:
    with patch("boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        client = BedrockAnthropicMessagesClient(model=model, aws_region=region)
    return client


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_bedrock_client_satisfies_protocol() -> None:
    """BedrockAnthropicMessagesClient satisfies DiagnosticLLMClient protocol."""
    client = _make_client()
    assert isinstance(client, DiagnosticLLMClient)


def test_bedrock_client_provider_name() -> None:
    assert _make_client().provider_name == "bedrock"


def test_bedrock_client_model_name_stored() -> None:
    client = _make_client(model="us.anthropic.claude-sonnet-4-6")
    assert client.model_name == "us.anthropic.claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


def test_empty_model_raises() -> None:
    with pytest.raises(CognitionLLMConfigurationError, match="model"):
        with patch("boto3.client"):
            BedrockAnthropicMessagesClient(model="", aws_region="us-east-1")


def test_empty_region_raises() -> None:
    with pytest.raises(CognitionLLMConfigurationError, match="LLM_AWS_REGION"):
        with patch("boto3.client"):
            BedrockAnthropicMessagesClient(
                model="global.anthropic.claude-haiku-4-5-20251001-v1:0", aws_region=""
            )


# ---------------------------------------------------------------------------
# Request / response translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_completion_returns_correct_result() -> None:
    """Bedrock converse() response is correctly translated to DiagnosticLLMCompletion."""
    with patch("boto3.client") as mock_boto:
        mock_bedrock = MagicMock()
        mock_boto.return_value = mock_bedrock
        mock_bedrock.converse.return_value = _fake_bedrock_response(
            text="This is the response.", input_tokens=20, output_tokens=8
        )
        client = BedrockAnthropicMessagesClient(
            model="global.anthropic.claude-haiku-4-5-20251001-v1:0",
            aws_region="us-east-1",
        )

    result = await client.complete(
        system_prompt="You are helpful.",
        messages=(DiagnosticLLMMessage(role="user", content="Hello"),),
        max_output_tokens=256,
        temperature=0.0,
    )

    assert isinstance(result, DiagnosticLLMCompletion)
    assert result.text == "This is the response."
    assert result.usage.prompt_tokens == 20
    assert result.usage.completion_tokens == 8
    assert result.usage.total_tokens == 28
    assert result.stop_reason == "end_turn"
    assert result.provider == "bedrock"


@pytest.mark.asyncio
async def test_converse_called_with_correct_shape() -> None:
    """converse() is called with system, messages, model, and inferenceConfig."""
    with patch("boto3.client") as mock_boto:
        mock_bedrock = MagicMock()
        mock_boto.return_value = mock_bedrock
        mock_bedrock.converse.return_value = _fake_bedrock_response()
        client = BedrockAnthropicMessagesClient(
            model="global.anthropic.claude-haiku-4-5-20251001-v1:0",
            aws_region="us-east-1",
        )

    await client.complete(
        system_prompt="Sys prompt",
        messages=(DiagnosticLLMMessage(role="user", content="User msg"),),
        max_output_tokens=512,
        temperature=0.0,
        tenant_id="tenant-test",
    )

    call_kwargs = mock_bedrock.converse.call_args.kwargs
    assert call_kwargs["modelId"] == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert call_kwargs["system"] == [{"text": "Sys prompt"}]
    assert call_kwargs["inferenceConfig"]["maxTokens"] == 512
    assert call_kwargs["inferenceConfig"]["temperature"] == 0.0
    assert call_kwargs["messages"][0]["role"] == "user"
    assert call_kwargs["messages"][0]["content"] == [{"text": "User msg"}]


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _make_bedrock_error(code: str, message: str = "error") -> Exception:
    from botocore.exceptions import ClientError

    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "Converse",
    )


@pytest.mark.asyncio
async def test_throttling_exception_raises_rate_limit_error() -> None:
    with patch("boto3.client") as mock_boto:
        mock_bedrock = MagicMock()
        mock_boto.return_value = mock_bedrock
        mock_bedrock.converse.side_effect = _make_bedrock_error("ThrottlingException")
        client = BedrockAnthropicMessagesClient(
            model="global.anthropic.claude-haiku-4-5-20251001-v1:0", aws_region="us-east-1"
        )

    with pytest.raises(ProviderRateLimitError):
        await client.complete(
            system_prompt="s",
            messages=(DiagnosticLLMMessage(role="user", content="x"),),
            max_output_tokens=100,
            temperature=0.0,
        )


@pytest.mark.asyncio
async def test_service_unavailable_raises_transient_error() -> None:
    with patch("boto3.client") as mock_boto:
        mock_bedrock = MagicMock()
        mock_boto.return_value = mock_bedrock
        mock_bedrock.converse.side_effect = _make_bedrock_error(
            "ServiceUnavailableException"
        )
        client = BedrockAnthropicMessagesClient(
            model="global.anthropic.claude-haiku-4-5-20251001-v1:0", aws_region="us-east-1"
        )

    with pytest.raises(ProviderTransientError):
        await client.complete(
            system_prompt="s",
            messages=(DiagnosticLLMMessage(role="user", content="x"),),
            max_output_tokens=100,
            temperature=0.0,
        )


@pytest.mark.asyncio
async def test_empty_response_raises_provider_error() -> None:
    """Empty content blocks → CognitionLLMProviderError."""
    with patch("boto3.client") as mock_boto:
        mock_bedrock = MagicMock()
        mock_boto.return_value = mock_bedrock
        mock_bedrock.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": []}},
            "usage": {"inputTokens": 1, "outputTokens": 0, "totalTokens": 1},
            "stopReason": "end_turn",
        }
        client = BedrockAnthropicMessagesClient(
            model="global.anthropic.claude-haiku-4-5-20251001-v1:0", aws_region="us-east-1"
        )

    with pytest.raises(CognitionLLMProviderError):
        await client.complete(
            system_prompt="s",
            messages=(DiagnosticLLMMessage(role="user", content="x"),),
            max_output_tokens=100,
            temperature=0.0,
        )


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def _settings_override(**kwargs: Any) -> Any:
    from app.core.config import Settings

    defaults: dict[str, Any] = {
        "LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_DEFAULT_MODEL": "claude-sonnet-4-6",
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        "ANTHROPIC_VERSION": "2023-06-01",
        "AI_TIMEOUT_SECONDS": 30.0,
        "LLM_AWS_REGION": "us-east-1",
        "BEDROCK_DEFAULT_MODEL": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        "BEDROCK_REASONING_MODEL": "us.anthropic.claude-sonnet-4-6",
    }
    defaults.update(kwargs)
    return Settings.model_construct(**defaults)  # type: ignore[attr-defined]


def test_factory_returns_deterministic_when_no_anthropic_key() -> None:
    from app.cognition.llm import DeterministicDiagnosticLLMClient

    settings = _settings_override(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
    client = build_llm_client(settings)
    assert isinstance(client, DeterministicDiagnosticLLMClient)


def test_factory_fails_closed_in_production_when_no_anthropic_key() -> None:
    settings = _settings_override(
        ENVIRONMENT="production",
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="",
    )

    with pytest.raises(CognitionLLMConfigurationError, match="ANTHROPIC_API_KEY"):
        build_llm_client(settings)


def test_factory_returns_anthropic_client_when_key_set() -> None:
    from app.cognition.llm import AnthropicMessagesClient

    settings = _settings_override(
        LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-test-key"
    )
    client = build_llm_client(settings)
    assert isinstance(client, AnthropicMessagesClient)
    assert client.model_name == "claude-sonnet-4-6"


def test_factory_returns_bedrock_client_when_provider_is_bedrock() -> None:
    settings = _settings_override(LLM_PROVIDER="bedrock", LLM_AWS_REGION="us-east-1")
    with patch("boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        client = build_llm_client(settings)
    assert isinstance(client, BedrockAnthropicMessagesClient)
    assert client.model_name == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert client.provider_name == "bedrock"


def test_factory_prefer_reasoning_model_selects_sonnet() -> None:
    settings = _settings_override(
        LLM_PROVIDER="bedrock",
        LLM_AWS_REGION="us-east-1",
        BEDROCK_REASONING_MODEL="us.anthropic.claude-sonnet-4-6",
    )
    with patch("boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        client = build_llm_client(settings, prefer_reasoning_model=True)
    assert isinstance(client, BedrockAnthropicMessagesClient)
    assert client.model_name == "us.anthropic.claude-sonnet-4-6"


def test_factory_default_model_selects_haiku() -> None:
    settings = _settings_override(
        LLM_PROVIDER="bedrock",
        LLM_AWS_REGION="us-east-1",
        BEDROCK_DEFAULT_MODEL="global.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    with patch("boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        client = build_llm_client(settings, prefer_reasoning_model=False)
    assert isinstance(client, BedrockAnthropicMessagesClient)
    assert client.model_name == "global.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_factory_bedrock_with_empty_region_returns_deterministic() -> None:
    """Empty region → LLM not configured → DeterministicDiagnosticLLMClient."""
    from app.cognition.llm import DeterministicDiagnosticLLMClient

    settings = _settings_override(LLM_PROVIDER="bedrock", LLM_AWS_REGION="")
    client = build_llm_client(settings)
    assert isinstance(client, DeterministicDiagnosticLLMClient)


def test_factory_bedrock_with_empty_region_fails_closed_in_production() -> None:
    settings = _settings_override(
        ENVIRONMENT="production",
        LLM_PROVIDER="bedrock",
        LLM_AWS_REGION="",
    )

    with pytest.raises(CognitionLLMConfigurationError, match="LLM_AWS_REGION"):
        build_llm_client(settings)


# ---------------------------------------------------------------------------
# Vendor isolation
# ---------------------------------------------------------------------------


def test_llm_bedrock_does_not_import_anthropic_sdk() -> None:
    """llm_bedrock.py must not contain top-level 'import anthropic' or 'from anthropic'.

    This enforces the Phase 5-C constitutional constraint: vendor SDKs stay
    out of the cognition package. Bedrock uses boto3 (allowed) instead.
    """
    bedrock_path = (
        Path(__file__).parent.parent / "app" / "cognition" / "llm_bedrock.py"
    )
    source = bedrock_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "anthropic", (
                    "llm_bedrock.py has a top-level 'import anthropic' — "
                    "boto3 must be used instead"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "anthropic" and not (
                node.module or ""
            ).startswith("anthropic."), (
                f"llm_bedrock.py imports from 'anthropic': {ast.dump(node)}"
            )
