"""SME Reviewer Agent (P2).

Instantiation of BaseGovernedLLMAgent that assembles a structured case
package for a human SME when:
  - FraudDetectionAgent returns risk_score ≥ threshold_high ("fraud_risk_high")
  - A complex eligibility case requires expert review

The agent is a CONTEXT-ENRICHMENT LAYER for a human decision, not a
decision-maker. It produces a structured SMECasePackage JSON that is
stored on the CaseApprovalRecord.metadata["sme_case_package"] field,
giving the human reviewer a complete, structured picture.

The human decides via the existing CaseApprovalService / ApprovalRecord
mechanism. The SME agent's recommended_resolution is advisory context in
the approval UI — NEVER an auto-approval. Every approval still requires:
  - governance_decision_id (Invariant 2)
  - human sign-off through CaseApprovalService.approve_case()

Integration seam: approval_tasks.review_case_approval_runtime() — runs
BEFORE CaseApprovalService.review_case() so the human reviewer sees the
full case package when the review begins. Fail-open: if the agent is
unavailable, the approval case proceeds with whatever context the SME
service already has; no blocking.

Output schema: SMECasePackage
  case_id:                  CaseApprovalRecord.approval_case_id
  ticket_summary:           concise summary of the ticket and what happened
  fraud_signal:             FraudSignal dict if present, null otherwise
  evidence_summary:         summary of the KB evidence cited in the reply
  lineage_trace:            key events in causal order (act, substrate, timestamp)
  recommended_resolution:   action + reasoning + confidence (advisory only)
  decision_options:         the four human actions available
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.governed.base import AgentInput, BaseGovernedLLMAgent
from app.agents.governed.policy import AgentPolicyRecord
from app.cognition.llm import DiagnosticLLMClient
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.tenant.persistence import TenantConfigurationRepository

logger = logging.getLogger(__name__)

SME_REVIEWER_POLICY_TYPE = "sme_reviewer"

# The four decisions a human SME can take — listed in case package so
# the reviewer's UI can render them without out-of-band knowledge.
SME_DECISION_OPTIONS = [
    "APPROVE_AS_IS",
    "EDIT_AND_APPROVE",
    "DENY",
    "ESCALATE_FURTHER",
]

SME_CASE_PACKAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "case_id",
        "ticket_summary",
        "fraud_signal",
        "evidence_summary",
        "lineage_trace",
        "recommended_resolution",
        "decision_options",
    ],
    "properties": {
        "case_id": {"type": "string"},
        "ticket_summary": {"type": "string", "maxLength": 1000},
        "fraud_signal": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "risk_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "signal_kinds": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "reasoning": {"type": "string"},
                    },
                },
            ]
        },
        "evidence_summary": {"type": "string", "maxLength": 1500},
        "lineage_trace": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "act": {"type": "string"},
                    "substrate": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        },
        "recommended_resolution": {
            "type": "object",
            "required": ["action", "reasoning", "confidence"],
            "properties": {
                "action": {"type": "string", "maxLength": 200},
                "reasoning": {"type": "string", "maxLength": 800},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
            "additionalProperties": False,
        },
        "decision_options": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "additionalProperties": False,
}


class SMEReviewerAgent(BaseGovernedLLMAgent):
    """Governed LLM agent that produces a structured SME case package.

    Runs once per approval case BEFORE the human reviewer opens it.
    Observational: produces context, never emits an approval decision.
    Fail-open: if agent unavailable, approval case proceeds without package.
    """

    policy_type = SME_REVIEWER_POLICY_TYPE
    operational_act = OperationalAct.SME_REVIEW_REQUEST
    output_schema = SME_CASE_PACKAGE_SCHEMA
    substrate = OperationalSubstrate.HUMAN

    max_output_tokens = 2048
    temperature = 0.0
    # Structured JSON output only — not shown to customers.
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
        case_id = content.get("case_id", "")
        ticket_text = content.get("ticket_text", "")
        proposed_reply = content.get("proposed_reply", "")
        fraud_signal = content.get("fraud_signal")
        citations = content.get("citations", [])
        lineage_events = content.get("lineage_events", [])
        extracted_fields = content.get("extracted_fields", {})
        entry_category = content.get("entry_category", "")
        recommended_actions = content.get("recommended_actions", [])

        parts = [
            f"## CASE\nCase ID: {case_id}\nEntry category: {entry_category}",
        ]

        if ticket_text:
            parts.append(f"## CUSTOMER TICKET\n{ticket_text}")

        if proposed_reply:
            parts.append(f"## PROPOSED REPLY\n{proposed_reply}")

        if fraud_signal:
            parts.append(
                f"## FRAUD SIGNAL\n```json\n{json.dumps(fraud_signal, indent=2)}\n```"
            )
        else:
            parts.append("## FRAUD SIGNAL\n(none detected)")

        if extracted_fields:
            parts.append(
                f"## EXTRACTED FIELDS\n```json\n{json.dumps(extracted_fields, indent=2)}\n```"
            )

        if citations:
            cit_parts = []
            for i, cit in enumerate(citations[:8], 1):
                title = cit.get("title", f"Citation {i}")
                excerpt = cit.get("safe_excerpt") or cit.get("content", "")
                score = cit.get("score", 0.0)
                cit_parts.append(f"### [{i}] {title} (score={score:.2f})\n{excerpt[:500]}")
            parts.append("## KNOWLEDGE CITATIONS\n" + "\n\n".join(cit_parts))
        else:
            parts.append("## KNOWLEDGE CITATIONS\n(none)")

        if recommended_actions:
            parts.append(
                f"## RECOMMENDED ACTIONS\n```json\n{json.dumps(recommended_actions[:5], indent=2)}\n```"
            )

        if lineage_events:
            event_lines = []
            for ev in lineage_events[:15]:
                act = ev.get("act", "")
                substrate = ev.get("substrate", "")
                ts = ev.get("timestamp", "")
                event_lines.append(f"- [{ts}] {substrate}:{act}")
            parts.append("## OPERATIONAL LINEAGE\n" + "\n".join(event_lines))

        parts.append(
            "## TASK\n"
            "You are assembling a structured case package for a human SME reviewer. "
            "The human must decide whether to APPROVE_AS_IS, EDIT_AND_APPROVE, DENY, "
            "or ESCALATE_FURTHER.\n\n"
            "Produce the SMECasePackage JSON:\n"
            "- ticket_summary: 2-3 sentences covering what the customer wants and what "
            "makes this case require human review\n"
            "- fraud_signal: copy the FRAUD SIGNAL block as-is, or null if none\n"
            "- evidence_summary: 2-3 sentences on whether the cited KB knowledge "
            "supports the proposed reply (or is absent/weak)\n"
            "- lineage_trace: list the key operational events in order "
            "(act, substrate, timestamp, one-line note)\n"
            "- recommended_resolution: your assessment of the best action "
            "(action=one of the decision_options, reasoning=why, confidence=0-1)\n"
            "- decision_options: always exactly "
            f"{json.dumps(SME_DECISION_OPTIONS)}\n\n"
            f"Use case_id = \"{case_id}\"."
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

        if not isinstance(parsed.get("case_id"), str):
            return None

        # Sanitize ticket_summary
        if not isinstance(parsed.get("ticket_summary"), str):
            parsed["ticket_summary"] = ""
        else:
            parsed["ticket_summary"] = parsed["ticket_summary"][:1000]

        # Sanitize evidence_summary
        if not isinstance(parsed.get("evidence_summary"), str):
            parsed["evidence_summary"] = ""
        else:
            parsed["evidence_summary"] = parsed["evidence_summary"][:1500]

        # Validate recommended_resolution
        rec = parsed.get("recommended_resolution")
        if not isinstance(rec, dict):
            parsed["recommended_resolution"] = {
                "action": "ESCALATE_FURTHER",
                "reasoning": "Case package assembly incomplete.",
                "confidence": 0.0,
            }
        else:
            confidence = rec.get("confidence", 0.0)
            if not isinstance(confidence, (int, float)):
                confidence = 0.0
            parsed["recommended_resolution"] = {
                "action": str(rec.get("action", "ESCALATE_FURTHER"))[:200],
                "reasoning": str(rec.get("reasoning", ""))[:800],
                "confidence": max(0.0, min(1.0, float(confidence))),
            }

        # Enforce decision_options — always exactly the canonical four
        parsed["decision_options"] = SME_DECISION_OPTIONS

        # Sanitize lineage_trace
        lineage = parsed.get("lineage_trace")
        if not isinstance(lineage, list):
            parsed["lineage_trace"] = []
        else:
            cleaned = []
            for item in lineage:
                if isinstance(item, dict):
                    cleaned.append({
                        "act": str(item.get("act", ""))[:100],
                        "substrate": str(item.get("substrate", ""))[:50],
                        "timestamp": str(item.get("timestamp", "")),
                        "note": str(item.get("note", ""))[:200],
                    })
            parsed["lineage_trace"] = cleaned

        return parsed

    def _check_money_goods(self, parsed: dict[str, Any]) -> bool:
        # SME case packages never contain money/goods commitments.
        # The human SME decides — the agent only assembles context.
        return False
