"""Diagnostic agent runtime."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict

from app.cognition.diagnostic_runtime import DiagnosticCognitionRuntime


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str
    category: str
    confidence: float
    provider: str | None = None
    model: str | None = None
    citations: tuple[int, ...] = ()
    usage_id: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_micro_usd: int = 0
    governance_decision_id: str | None = None
    cognition_audit_id: str | None = None


class DiagnosticAgent:
    """Bounded support-ticket diagnostic runtime.

    Phase 5-C routes live worker executions through
    ``DiagnosticCognitionRuntime`` for RAG-grounded LLM reasoning. The
    local heuristic fallback exists only for legacy direct construction
    in tests and offline tooling that has not supplied the runtime yet.
    """

    def __init__(
        self,
        *,
        cognition_runtime: DiagnosticCognitionRuntime | None = None,
    ) -> None:
        self._cognition_runtime = cognition_runtime

    async def execute(
        self,
        dispatch_id: str,
        session_id: str,
        tenant_id: str,
        content: str,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> DiagnosticResult:
        if self._cognition_runtime is not None and execution_id is not None:
            result = await self._cognition_runtime.reason_about_ticket(
                tenant_id=tenant_id,
                execution_id=execution_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                content=content,
                attempt_id=attempt_id,
            )
            return DiagnosticResult(
                summary=result.summary,
                category=result.category,
                confidence=result.confidence,
                provider=result.provider,
                model=result.model,
                citations=result.citations,
                usage_id=str(result.usage_id),
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                estimated_cost_micro_usd=result.estimated_cost_micro_usd,
                governance_decision_id=result.governance_decision_id,
                cognition_audit_id=_optional_metadata_str(
                    result.metadata,
                    "cognition_audit_id",
                ),
            )
        normalized = content.casefold()
        category, confidence = _classify(normalized)
        return DiagnosticResult(
            summary=(
                "Deterministic diagnostic classified "
                f"dispatch {dispatch_id} for session {session_id} "
                f"under tenant {tenant_id} as {category}."
            ),
            category=category,
            confidence=confidence,
        )


def _classify(content: str) -> tuple[str, float]:
    if _contains_any(
        content,
        (
            "charge",
            "charging",
            "charger",
            "battery",
            "powercore",
            "power bank",
            "cable",
        ),
    ):
        return "charging_issue", 0.92
    if _contains_any(
        content,
        (
            "connect",
            "connection",
            "connectivity",
            "bluetooth",
            "wifi",
            "wi-fi",
            "pair",
            "network",
        ),
    ):
        return "connectivity_issue", 0.86
    if _contains_any(
        content,
        (
            "account",
            "login",
            "log in",
            "password",
            "billing",
            "subscription",
            "invoice",
        ),
    ):
        return "account_issue", 0.84
    return "unknown_issue", 0.35


def _contains_any(content: str, needles: tuple[str, ...]) -> bool:
    return any(needle in content for needle in needles)


def _optional_metadata_str(metadata: Mapping[str, Any], key: str) -> str | None:
    value: Any | None = metadata.get(key)
    return str(value) if value is not None else None


__all__ = ["DiagnosticAgent", "DiagnosticResult"]
