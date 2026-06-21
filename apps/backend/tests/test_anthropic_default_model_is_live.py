"""Regression coverage for the retired ANTHROPIC_DEFAULT_MODEL default.

config.py's ANTHROPIC_DEFAULT_MODEL previously hardcoded a retired model id
(claude-sonnet-4-20250514, confirmed via a real Anthropic API call to return
HTTP 404 not_found_error). Production only survived because Fly has an env
override set — any environment without that override (a fresh deploy, a new
worker, CI, a teammate's local setup) would 404 on every diagnostic call.
This pins the code-level default so that regression can't reappear silently.
"""

from __future__ import annotations

import os

import pytest

from app.cognition.llm import AnthropicMessagesClient, DiagnosticLLMMessage
from app.core.config import Settings

# Confirmed retired via a direct Anthropic API call returning
# {"type":"error","error":{"type":"not_found_error", ...}}.
_RETIRED_MODEL_IDS = frozenset({"claude-sonnet-4-20250514"})

requires_live_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason=(
        "requires ANTHROPIC_API_KEY to prove the code-level default model "
        "id is actually live against the real Anthropic API."
    ),
)


def test_default_anthropic_model_is_not_a_retired_id() -> None:
    field = Settings.model_fields["ANTHROPIC_DEFAULT_MODEL"]
    assert field.default not in _RETIRED_MODEL_IDS


def test_default_anthropic_model_matches_the_confirmed_live_id() -> None:
    # Pinned to the exact id confirmed running in production (the value
    # Fly's ANTHROPIC_DEFAULT_MODEL override is set to) — not a guess.
    field = Settings.model_fields["ANTHROPIC_DEFAULT_MODEL"]
    assert field.default == "claude-sonnet-4-6"


@requires_live_anthropic
@pytest.mark.asyncio
async def test_live_call_with_unset_env_override_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates the exact failure scenario: an environment with no
    ANTHROPIC_DEFAULT_MODEL override (fresh deploy / new worker / a
    teammate's setup) must still resolve to a live model, not 404."""
    monkeypatch.delenv("ANTHROPIC_DEFAULT_MODEL", raising=False)
    settings = Settings()
    assert settings.ANTHROPIC_DEFAULT_MODEL not in _RETIRED_MODEL_IDS

    client = AnthropicMessagesClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model=settings.ANTHROPIC_DEFAULT_MODEL,
    )
    completion = await client.complete(
        system_prompt="Reply with exactly one word: ack.",
        messages=(DiagnosticLLMMessage(role="user", content="ping"),),
        max_output_tokens=8,
        temperature=0.0,
    )
    assert completion.text.strip()
