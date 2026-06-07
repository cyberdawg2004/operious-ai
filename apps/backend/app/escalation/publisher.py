"""Escalation transport publisher boundary."""

from __future__ import annotations

from typing import Protocol


class EscalationPublisher(Protocol):
    """Transport boundary for governance handoff work."""

    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None: ...

    async def publish_governance_escalation(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None: ...


__all__ = ["EscalationPublisher"]
