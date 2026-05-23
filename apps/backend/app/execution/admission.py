"""Execution admission tokens minted by governance."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class GovernanceAdmissionToken:
    """Durable proof that governance admitted an execution intent."""

    governance_decision_id: uuid.UUID
    execution_governance_evaluation_id: uuid.UUID
    admitted_at: datetime
    tenant_id: str


__all__ = ["GovernanceAdmissionToken"]
