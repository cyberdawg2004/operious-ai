"""Agent proposal — the result of a governed LLM agent run."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class AgentProposalStatus(StrEnum):
    """Fail-closed status values for governed agent output."""

    COMPLETED = "completed"
    REQUIRE_APPROVAL = "require_approval"
    PENDING_HUMAN_APPROVAL = "pending_human_approval"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class AgentProposal:
    """The result of BaseGovernedLLMAgent.run() — never raises."""

    status: AgentProposalStatus
    output: Mapping[str, Any] | None = None
    reason: str = ""
    governance_decision_id: uuid.UUID | None = None
    invocation_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
