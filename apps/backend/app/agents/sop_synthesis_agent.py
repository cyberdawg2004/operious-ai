"""SOP improvement synthesis agent."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import ValidationError

from app.cognition.exceptions import CognitionLLMProviderError
from app.cognition.llm import DiagnosticLLMClient, DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.cognition.sop_improvement_models import SOPImprovementLLMOutput
from app.knowledge.runtime import KnowledgeRuntime

_SYSTEM_PROMPT = (
    "You are a customer support SOP specialist. Analyze the following "
    "failure pattern and existing SOP documentation, then propose a "
    "specific improvement. Respond only with valid JSON matching this "
    "schema: {schema}"
)


@dataclass(frozen=True, slots=True)
class SOPSynthesisConfig:
    max_output_tokens: int = 768
    temperature: float = 0.0


class SOPSynthesisAgent:
    """
    Synthesizes a specific SOP improvement proposal from failure-pattern
    context plus existing SOP document content.
    """

    def __init__(
        self,
        *,
        llm_client: DiagnosticLLMClient,
        knowledge_runtime: KnowledgeRuntime,
        config: SOPSynthesisConfig | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._knowledge_runtime = knowledge_runtime
        self._config = config or SOPSynthesisConfig()

    async def synthesize_improvement(
        self,
        *,
        category: str,
        failure_count: int,
        failure_description: str,
        tenant_id: str,
    ) -> str:
        """
        Return LLM-synthesized SOP addition text, falling back to static
        proposal text on retrieval, provider, parsing, or validation failure.
        """

        try:
            retrieval = await self._knowledge_runtime.retrieve(
                tenant_id=tenant_id,
                query=f"{category} handling procedure",
                top_k=5,
            )
            prompt = _render_user_prompt(
                category=category,
                failure_count=failure_count,
                failure_description=failure_description,
                excerpts=tuple(item.content for item in retrieval.items),
            )
            completion = await self._llm_client.complete(
                system_prompt=_render_system_prompt(),
                messages=(DiagnosticLLMMessage(role="user", content=prompt),),
                max_output_tokens=self._config.max_output_tokens,
                temperature=self._config.temperature,
                tenant_id=tenant_id,
            )
            output = _parse_output(completion.text)
            return output.proposed_sop_addition
        except Exception:
            return _sop_fallback_text(category, failure_count)


class DeterministicSOPImprovementLLMClient:
    """Deterministic local SOP synthesis LLM for tests and offline workers."""

    provider_name = "operious-deterministic-llm"
    model_name = "operious-sop-improvement-local-v1"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, max_output_tokens, temperature, tenant_id
        prompt = "\n".join(message.content for message in messages)
        category = _prompt_value(prompt, "Category") or "unknown_diagnostic"
        occurrences = _prompt_value(prompt, "Occurrences") or "repeated failures"
        addition = (
            f"When handling {category}, agents must verify the diagnostic "
            "symptom, follow the documented escalation criteria, capture "
            "customer-visible impact, and document the resolution decision "
            "before closing the ticket."
        )
        payload = {
            "improvement_title": f"Improve {category} handling",
            "problem_statement": (
                f"The SOP does not give enough concrete guidance for "
                f"{occurrences} tied to {category}."
            ),
            "proposed_sop_addition": addition,
            "rationale": (
                "A specific checklist reduces repeated misses and gives "
                "agents a reviewable closure standard."
            ),
            "affected_sop_section": category,
            "confidence": 0.72,
        }
        text = json.dumps(payload, sort_keys=True)
        prompt_tokens = _estimate_tokens(prompt)
        completion_tokens = _estimate_tokens(text)
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            raw_metadata={"deterministic": True},
        )


def _render_system_prompt() -> str:
    schema = json.dumps(
        SOPImprovementLLMOutput.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
    )
    return _SYSTEM_PROMPT.replace("{schema}", schema)


def _render_user_prompt(
    *,
    category: str,
    failure_count: int,
    failure_description: str,
    excerpts: tuple[str, ...],
) -> str:
    numbered = "\n".join(
        f"{index}. {excerpt.strip()}"
        for index, excerpt in enumerate(excerpts, start=1)
        if excerpt.strip()
    )
    if not numbered:
        numbered = "No current SOP excerpts were retrieved."
    return "\n\n".join(
        (
            "FAILURE PATTERN",
            f"Category: {category}",
            f"Occurrences: {failure_count} tickets in the last 24 hours",
            failure_description,
            "CURRENT SOP EXCERPTS",
            numbered,
            (
                "Propose a specific addition to the SOP that would help "
                "agents handle this category of issues more effectively."
            ),
        )
    )


def _parse_output(text: str) -> SOPImprovementLLMOutput:
    try:
        raw = json.loads(_extract_json(text))
    except json.JSONDecodeError as exc:
        raise CognitionLLMProviderError(
            "SOP improvement model returned invalid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise CognitionLLMProviderError(
            "SOP improvement model returned non-object JSON"
        )
    try:
        return SOPImprovementLLMOutput.model_validate(cast(dict[str, Any], raw))
    except ValidationError as exc:
        raise CognitionLLMProviderError(
            "SOP improvement model output failed schema validation"
        ) from exc


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _sop_fallback_text(category: str, failure_count: int) -> str:
    return (
        f"Propose updating the SOP for repeated QA failures in {category}. "
        f"Failure signals flagged this category {failure_count} times in the "
        "configured lookback window; review the SOP guidance and add "
        "corrective operator steps."
    )


def _prompt_value(prompt: str, label: str) -> str | None:
    match = re.search(rf"^{re.escape(label)}:\s*(.+)$", prompt, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


__all__ = [
    "DeterministicSOPImprovementLLMClient",
    "SOPSynthesisAgent",
    "SOPSynthesisConfig",
]
