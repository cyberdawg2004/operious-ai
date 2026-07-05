"""Governed LLM agent scaffold — CORE pattern (P1a).

Every intelligence-layer agent is an instantiation of BaseGovernedLLMAgent.
The scaffold owns governance, persistence, fail-closed, and domain-agnosticism.
Subclasses provide only: policy_type, output_schema, operational_act, and
parse-specific logic.
"""

from app.agents.governed.base import BaseGovernedLLMAgent
from app.agents.governed.governance import build_agent_governance_runtime
from app.agents.governed.proposal import AgentProposal, AgentProposalStatus

__all__ = [
    "AgentProposal",
    "AgentProposalStatus",
    "BaseGovernedLLMAgent",
    "build_agent_governance_runtime",
]
