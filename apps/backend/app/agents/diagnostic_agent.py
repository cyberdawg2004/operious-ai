"""Deterministic diagnostic agent runtime."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str
    category: str
    confidence: float


class DiagnosticAgent:
    """Bounded support-ticket diagnostic runtime.

    This agent is intentionally heuristic-only for PR_W4. It performs
    no model calls, tool calls, planning, or autonomous loops.
    """

    async def execute(
        self,
        dispatch_id: str,
        session_id: str,
        tenant_id: str,
        content: str,
    ) -> DiagnosticResult:
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


__all__ = ["DiagnosticAgent", "DiagnosticResult"]
