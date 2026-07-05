"""MVP-5 — KB Trainer Agent.

Instantiation of BaseGovernedLLMAgent that generates a KBImprovementProposal
when the QA signal aggregator identifies a category with consistently low
semantic grounding scores.

The agent is a PROPOSAL GENERATOR — it never writes to the KB directly.
Every proposal routes to the KB admin review queue via the existing
TenantConfigurationRuntime.create_knowledge_document() + ApprovalRecord
mechanism. The human admin approves. MVP-4's contradiction check fires on
the new/amended document before it enters the active KB.

This closes the QA→Trainer→KB loop:
  QA scores weak → Aggregator identifies category → Trainer proposes KB improvement
  → Human approves → KB updated → Future QA scores improve for that category

Inputs (via AgentInput.content):
  category:              the resolution category with weak QA scores
  avg_semantic_grounding: float 0–1, average grounding score over window
  ticket_count:          how many tickets contributed
  representative_cases:  list of {ticket_text, proposed_reply, citations, score}
  current_kb_docs:       list of {doc_id, title, content} — active docs for category
  tenant_id:             (in AgentInput.tenant_id)

Output schema: KBImprovementProposal
  improvement_type:     "NEW_DOCUMENT" | "AMENDMENT" | "GAP_NOTICE"
  target_document_id:   str | null — existing doc to amend (null for NEW_DOCUMENT)
  proposed_content:     str | null — full text of new/amended document
  gap_description:      str | null — describes the gap (used for GAP_NOTICE)
  evidence_case_ids:    list[str] — representative case IDs used as evidence
  confidence:           0.0–1.0

Improvement types:
  NEW_DOCUMENT: Trainer identifies a gap that needs an entirely new KB article
  AMENDMENT:    Trainer identifies an existing doc that needs updating
  GAP_NOTICE:   Trainer cannot produce specific content but signals a gap
                for operator attention (lowest commitment, always safe)
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import Any

from app.agents.governed.base import AgentInput, BaseGovernedLLMAgent
from app.agents.governed.policy import AgentPolicyRecord
from app.cognition.llm import DiagnosticLLMClient
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.governance.enums import EnforcementStage
from app.tenant.persistence import TenantConfigurationRepository

logger = logging.getLogger(__name__)

KB_TRAINER_POLICY_TYPE = "kb_trainer"

_MAX_CONTENT_CHARS = 8000
_MAX_CASES = 5
_MAX_KB_DOCS = 8


class KBImprovementType(StrEnum):
    """Type of KB improvement proposed by the trainer."""

    NEW_DOCUMENT = "NEW_DOCUMENT"
    AMENDMENT = "AMENDMENT"
    GAP_NOTICE = "GAP_NOTICE"


KB_IMPROVEMENT_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "improvement_type",
        "target_document_id",
        "proposed_content",
        "gap_description",
        "evidence_case_ids",
        "confidence",
    ],
    "properties": {
        "improvement_type": {
            "type": "string",
            "enum": [t.value for t in KBImprovementType],
        },
        "target_document_id": {"type": ["string", "null"]},
        "proposed_content": {"type": ["string", "null"]},
        "gap_description": {"type": ["string", "null"]},
        "evidence_case_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": False,
}


class KBTrainerAgent(BaseGovernedLLMAgent):
    """Governed LLM agent that proposes KB improvements based on QA signal patterns.

    Runs in daily batch via aggregate_qa_signals task. Fail-closed: any error
    routes to REQUIRE_APPROVAL (human decides whether to act on the signal).
    Never writes to KB directly — always produces a proposal for human review.
    """

    policy_type = KB_TRAINER_POLICY_TYPE
    operational_act = OperationalAct.KB_TRAINER_PROPOSE
    output_schema = KB_IMPROVEMENT_PROPOSAL_SCHEMA
    substrate = OperationalSubstrate.AGENTS
    enforcement_stage = EnforcementStage.PRE_GROUNDING

    max_output_tokens = 4096
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
        category = content.get("category", "")
        avg_grounding = content.get("avg_semantic_grounding", 0.0)
        ticket_count = content.get("ticket_count", 0)
        representative_cases = content.get("representative_cases", [])
        current_kb_docs = content.get("current_kb_docs", [])

        parts = [
            f"## QA SIGNAL\n"
            f"Category: {category}\n"
            f"Average semantic grounding: {avg_grounding:.2f}\n"
            f"Ticket count in window: {ticket_count}\n"
            f"This category's replies are not well-grounded by the current KB.",
        ]

        if representative_cases:
            case_parts = []
            for i, case in enumerate(representative_cases[:_MAX_CASES], 1):
                ticket = case.get("ticket_text", "")[:1000]
                reply = case.get("proposed_reply", "")[:500]
                score = case.get("semantic_grounding", 0.0)
                case_id = case.get("case_id", f"case-{i}")
                cited_docs = case.get("cited_titles", [])
                case_parts.append(
                    f"### Case {case_id} (grounding={score:.2f})\n"
                    f"Ticket: {ticket}\n"
                    f"Reply: {reply}\n"
                    f"Cited: {cited_docs}"
                )
            parts.append("## REPRESENTATIVE CASES\n" + "\n\n".join(case_parts))
        else:
            parts.append("## REPRESENTATIVE CASES\n(none provided)")

        if current_kb_docs:
            doc_parts = []
            for doc in current_kb_docs[:_MAX_KB_DOCS]:
                doc_id = doc.get("doc_id", "")
                title = doc.get("title", "")
                doc_content = doc.get("content", "")[:2000]
                doc_parts.append(f"### [{doc_id}] {title}\n{doc_content}")
            parts.append("## CURRENT KB DOCUMENTS FOR THIS CATEGORY\n" + "\n\n".join(doc_parts))
        else:
            parts.append("## CURRENT KB DOCUMENTS FOR THIS CATEGORY\n(none found)")

        parts.append(
            "## TASK\n"
            "The QA scores show that replies in this category are not well-grounded "
            "by the current KB. You must identify WHY and propose a specific KB improvement.\n\n"
            "Choose the improvement type:\n"
            "- NEW_DOCUMENT: propose a new KB article that would ground future replies. "
            "Set proposed_content to the full article text.\n"
            "- AMENDMENT: propose updating an existing document. Set target_document_id "
            "and proposed_content to the full updated document text.\n"
            "- GAP_NOTICE: you cannot produce specific content but can describe the gap. "
            "Set gap_description. Use this if KB docs exist but you cannot determine "
            "what specific content is missing.\n\n"
            "Rules:\n"
            "- proposed_content must be factual and grounded in the evidence cases. "
            "Do not invent facts, thresholds, or policies.\n"
            "- If you cannot identify a clear improvement, use GAP_NOTICE with a precise "
            "description. A honest GAP_NOTICE is better than an inaccurate NEW_DOCUMENT.\n"
            "- evidence_case_ids: list the case IDs you used as evidence.\n"
            "- confidence: 0.0=not confident, 1.0=highly confident the proposal "
            "would improve grounding scores."
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

        improvement_type = parsed.get("improvement_type")
        valid_types = {t.value for t in KBImprovementType}
        if improvement_type not in valid_types:
            # Default to GAP_NOTICE — always safe
            parsed["improvement_type"] = KBImprovementType.GAP_NOTICE.value

        confidence = parsed.get("confidence")
        if not isinstance(confidence, (int, float)):
            parsed["confidence"] = 0.0
        else:
            parsed["confidence"] = max(0.0, min(1.0, float(confidence)))

        if not isinstance(parsed.get("evidence_case_ids"), list):
            parsed["evidence_case_ids"] = []

        # Enforce: proposed_content and gap_description must be str or null
        for field in ("proposed_content", "gap_description", "target_document_id"):
            v = parsed.get(field)
            if v is not None and not isinstance(v, str):
                parsed[field] = str(v)

        # Truncate content to stay within KB size limits
        if isinstance(parsed.get("proposed_content"), str):
            parsed["proposed_content"] = parsed["proposed_content"][:_MAX_CONTENT_CHARS]

        if isinstance(parsed.get("gap_description"), str):
            parsed["gap_description"] = parsed["gap_description"][:2000]

        return parsed

    def _check_money_goods(self, parsed: dict[str, Any]) -> bool:
        # KB improvement proposals never contain money/goods commitments.
        # The human admin reviews the proposed content before it enters the KB.
        return False
