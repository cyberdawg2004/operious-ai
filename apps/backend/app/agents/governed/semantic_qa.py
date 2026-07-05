"""MVP-6 — Semantic QA Agent.

Instantiation of BaseGovernedLLMAgent that scores whether the cited KB
excerpts actually support the claims made in a resolution reply.

The existing QAAgentRuntime scores deterministic dimensions (timeline,
governance, policy compliance). This agent adds the semantic dimension:
did the LLM cite relevant knowledge, or did it generate claims that aren't
supported by what was retrieved?

Observational: never blocks a proposal. Never changes a proposal status.
Runs post-resolution and enriches the QAScoreRecord with semantic_grounding.

Integration seam: qa_tasks.score_supervisor_inspection_runtime() — runs
after build_qa_score_record(), before SOP/trainer queuing. If the agent is
unavailable (any failure), the QA score proceeds without semantic grounding
(0.0 default). The deterministic dimensions are the safety floor.

Output schema: SemanticQAResult
  proposal_id:              the resolution proposal this scores
  claim_scores:             per-claim grounding scores (list)
    segment_id:             identity label for the claim segment
    relevance_score:        0.0–1.0 how well citations support this claim
    reason:                 one-line explanation
  overall_semantic_grounding: 0.0–1.0 aggregate across all claims
  grounding_verdict:        STRONG | ADEQUATE | WEAK | MISSING

Grounding thresholds:
  STRONG:   overall_semantic_grounding ≥ 0.80
  ADEQUATE: overall_semantic_grounding ≥ 0.50
  WEAK:     overall_semantic_grounding ≥ 0.20
  MISSING:  overall_semantic_grounding < 0.20 (or no citations)
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from app.agents.governed.base import AgentInput, BaseGovernedLLMAgent
from app.agents.governed.policy import AgentPolicyRecord
from app.cognition.llm import DiagnosticLLMClient
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.qa.enums import SemanticGroundingVerdict
from app.tenant.persistence import TenantConfigurationRepository

logger = logging.getLogger(__name__)

SEMANTIC_QA_POLICY_TYPE = "semantic_qa"

_VERDICT_THRESHOLDS = {
    SemanticGroundingVerdict.STRONG:   0.80,
    SemanticGroundingVerdict.ADEQUATE: 0.50,
    SemanticGroundingVerdict.WEAK:     0.20,
}

SEMANTIC_QA_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "proposal_id",
        "claim_scores",
        "overall_semantic_grounding",
        "grounding_verdict",
    ],
    "properties": {
        "proposal_id": {"type": "string"},
        "claim_scores": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["segment_id", "relevance_score", "reason"],
                "properties": {
                    "segment_id": {"type": "string"},
                    "relevance_score": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "reason": {"type": "string", "maxLength": 300},
                },
                "additionalProperties": False,
            },
        },
        "overall_semantic_grounding": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "grounding_verdict": {
            "type": "string",
            "enum": [v.value for v in SemanticGroundingVerdict],
        },
    },
    "additionalProperties": False,
}


class SemanticQAAgent(BaseGovernedLLMAgent):
    """Governed LLM agent for semantic citation grounding quality.

    Runs post-resolution after QAAgentRuntime.score_inspection() completes.
    Observational: produces a SemanticQAResult but never alters the proposal
    status or blocks any flow. Failure routes to REQUIRE_APPROVAL, which
    the QA worker treats as 'grounding score unavailable' and proceeds.
    """

    policy_type = SEMANTIC_QA_POLICY_TYPE
    operational_act = OperationalAct.QA_SCORE
    output_schema = SEMANTIC_QA_RESULT_SCHEMA
    substrate = OperationalSubstrate.QA

    max_output_tokens = 1024
    temperature = 0.0
    # Observational: JSON output never shown to customers.
    skip_semantic_drift_check = True

    def __init__(
        self,
        *,
        llm_client: DiagnosticLLMClient,
        tenant_configuration_repository: TenantConfigurationRepository,
    ) -> None:
        super().__init__(
            llm_client=llm_client,
            tenant_configuration_repository=tenant_configuration_repository,
        )

    def build_user_content(
        self, agent_input: AgentInput, policy: AgentPolicyRecord
    ) -> str:
        content = agent_input.content
        proposal_id = content.get("proposal_id", "")
        reply_text = content.get("reply_text", "")
        citations = content.get("citations", [])

        parts = [
            f"## RESOLUTION REPLY\nProposal: {proposal_id}\n\n{reply_text}",
        ]

        if citations:
            citation_parts: list[str] = []
            for i, cit in enumerate(cast("list[Any]", citations), 1):
                cit_d: dict[str, Any] = cast("dict[str, Any]", cit)
                title = cit_d.get("title", f"Document {i}")
                excerpt = cit_d.get("safe_excerpt") or cit_d.get("content", "")
                score = cit_d.get("score", 0.0)
                citation_parts.append(
                    f"### Citation {i}: {title} (relevance score={score:.2f})\n{excerpt}"
                )
            parts.append("## KNOWLEDGE BASE CITATIONS\n" + "\n\n".join(citation_parts))
        else:
            parts.append("## KNOWLEDGE BASE CITATIONS\n(no citations provided)")

        parts.append(
            "## TASK\n"
            "Score how well the KNOWLEDGE BASE CITATIONS semantically support "
            "the claims made in the RESOLUTION REPLY.\n\n"
            "For each distinct claim or factual statement in the reply, assess "
            "whether the cited KB excerpts actually ground that claim. A claim "
            "is 'grounded' if a citation directly supports it. A claim is "
            "'ungrounded' if the citations are irrelevant or missing.\n\n"
            "Score each claim 0.0–1.0:\n"
            "  1.0: citation directly and specifically supports this claim\n"
            "  0.7: citation partially supports, minor gaps\n"
            "  0.3: citation loosely relates but does not directly support\n"
            "  0.0: no relevant citation found\n\n"
            "Compute overall_semantic_grounding as the average of all claim scores.\n"
            "Set grounding_verdict based on overall_semantic_grounding:\n"
            "  STRONG:   ≥ 0.80\n"
            "  ADEQUATE: ≥ 0.50\n"
            "  WEAK:     ≥ 0.20\n"
            "  MISSING:  < 0.20 or no citations\n\n"
            f"Use proposal_id = \"{proposal_id}\"."
        )
        return "\n\n".join(parts)

    def parse_output(self, raw_text: str) -> dict[str, Any] | None:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if "```" in text:
                text = text[:text.index("```")].strip()

        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(parsed, dict):
            return None

        d: dict[str, Any] = cast("dict[str, Any]", parsed)

        if not isinstance(d.get("proposal_id"), str):
            return None

        overall: Any = d.get("overall_semantic_grounding")
        if not isinstance(overall, (int, float)):
            return None
        d["overall_semantic_grounding"] = max(0.0, min(1.0, float(overall)))

        verdict: Any = d.get("grounding_verdict")
        valid_verdicts = {v.value for v in SemanticGroundingVerdict}
        if verdict not in valid_verdicts:
            # Derive verdict from score if model gave a wrong value
            d["grounding_verdict"] = score_to_verdict(
                d["overall_semantic_grounding"]
            ).value

        claim_scores: Any = d.get("claim_scores")
        if not isinstance(claim_scores, list):
            d["claim_scores"] = []
        else:
            cleaned: list[dict[str, Any]] = []
            for item in cast("list[Any]", claim_scores):
                if not isinstance(item, dict):
                    continue
                item_d: dict[str, Any] = cast("dict[str, Any]", item)
                relevance: Any = item_d.get("relevance_score", 0.0)
                if not isinstance(relevance, (int, float)):
                    relevance = 0.0
                cleaned.append({
                    "segment_id": str(item_d.get("segment_id", "")),
                    "relevance_score": max(0.0, min(1.0, float(relevance))),
                    "reason": str(item_d.get("reason", ""))[:300],
                })
            d["claim_scores"] = cleaned

        return d

    def _check_money_goods(self, parsed: dict[str, Any]) -> bool:
        # Semantic QA output is a grounding score. No money/goods commitment possible.
        return False


def score_to_verdict(overall_semantic_grounding: float) -> SemanticGroundingVerdict:
    """Map a 0.0–1.0 grounding score to a SemanticGroundingVerdict."""
    if overall_semantic_grounding >= _VERDICT_THRESHOLDS[SemanticGroundingVerdict.STRONG]:
        return SemanticGroundingVerdict.STRONG
    if overall_semantic_grounding >= _VERDICT_THRESHOLDS[SemanticGroundingVerdict.ADEQUATE]:
        return SemanticGroundingVerdict.ADEQUATE
    if overall_semantic_grounding >= _VERDICT_THRESHOLDS[SemanticGroundingVerdict.WEAK]:
        return SemanticGroundingVerdict.WEAK
    return SemanticGroundingVerdict.MISSING


def extract_semantic_grounding_score(proposal: dict[str, Any]) -> float:
    """Extract the overall_semantic_grounding float from a SemanticQAResult dict."""
    val = proposal.get("overall_semantic_grounding", 0.0)
    if not isinstance(val, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(val)))
