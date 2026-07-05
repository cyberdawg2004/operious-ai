"""MVP-4 — SOP Contradiction Agent.

Instantiation of BaseGovernedLLMAgent that detects semantic contradictions
between a new knowledge document and the tenant's active SOP/POLICY corpus.

Runs during KnowledgeRuntime.ingest_document() AFTER the injection scanner
passes, BEFORE the document is indexed into the vector store. A contradiction
finding keeps the document in QUARANTINE with contradiction_flagged reason.
Human reviews the ContradictionReport and resolves it before approving.

Domain-agnostic: no vertical-specific logic. The contradiction types are
structural (DIRECT_CONFLICT, SCOPE_OVERLAP, TEMPORAL_CONFLICT) and apply
to any tenant's KB corpus.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import Any, cast

from app.agents.governed.base import AgentInput, BaseGovernedLLMAgent
from app.agents.governed.policy import AgentPolicyRecord
from app.cognition.llm import DiagnosticLLMClient
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.tenant.persistence import TenantConfigurationRepository

logger = logging.getLogger(__name__)

SOP_CONTRADICTION_POLICY_TYPE = "sop_contradiction"

_MAX_CORPUS_DOCUMENTS = 20
_MAX_DOCUMENT_CHARS = 4000


class ContradictionType(StrEnum):
    """Structural contradiction categories."""

    DIRECT_CONFLICT = "direct_conflict"
    SCOPE_OVERLAP = "scope_overlap"
    TEMPORAL_CONFLICT = "temporal_conflict"


CONTRADICTION_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["document_id", "has_contradiction", "contradicting_documents"],
    "properties": {
        "document_id": {"type": "string"},
        "has_contradiction": {"type": "boolean"},
        "contradicting_documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "doc_id", "excerpt", "contradicting_excerpt",
                    "contradiction_type", "confidence",
                ],
                "properties": {
                    "doc_id": {"type": "string"},
                    "excerpt": {"type": "string"},
                    "contradicting_excerpt": {"type": "string"},
                    "contradiction_type": {
                        "type": "string",
                        "enum": [t.value for t in ContradictionType],
                    },
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


class SOPContradictionAgent(BaseGovernedLLMAgent):
    """Governed LLM agent for SOP/POLICY contradiction detection.

    Runs during KB ingest AFTER injection scan. Observational: it proposes
    a contradiction verdict; the KnowledgeRuntime acts on it by keeping the
    document in QUARANTINE. Agent failure → document proceeds to normal
    PENDING_REVIEW (conservative: don't block ingest on agent unavailability).
    """

    policy_type = SOP_CONTRADICTION_POLICY_TYPE
    operational_act = OperationalAct.SOP_CONTRADICTION_FLAG
    output_schema = CONTRADICTION_REPORT_SCHEMA
    substrate = OperationalSubstrate.AGENTS

    max_output_tokens = 2048
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
        new_doc_id = content.get("new_document_id", "")
        new_doc_title = content.get("new_document_title", "")
        new_doc_type = content.get("new_document_type", "")
        new_doc_content = content.get("new_document_content", "")
        corpus_documents = content.get("corpus_documents", [])

        if len(new_doc_content) > _MAX_DOCUMENT_CHARS:
            new_doc_content = new_doc_content[:_MAX_DOCUMENT_CHARS] + "\n[truncated]"

        parts = [
            f"## NEW DOCUMENT\n"
            f"ID: {new_doc_id}\n"
            f"Title: {new_doc_title}\n"
            f"Type: {new_doc_type}\n\n"
            f"{new_doc_content}",
        ]

        if corpus_documents:
            corpus_parts: list[str] = []
            for doc in cast("list[Any]", corpus_documents)[:_MAX_CORPUS_DOCUMENTS]:
                doc_d: dict[str, Any] = cast("dict[str, Any]", doc)
                doc_id = doc_d.get("doc_id", "")
                doc_title = doc_d.get("title", "")
                doc_content = str(doc_d.get("content", ""))
                if len(doc_content) > _MAX_DOCUMENT_CHARS:
                    doc_content = doc_content[:_MAX_DOCUMENT_CHARS] + "\n[truncated]"
                corpus_parts.append(
                    f"### [{doc_id}] {doc_title}\n{doc_content}"
                )
            parts.append(
                "## EXISTING CORPUS DOCUMENTS\n" + "\n\n".join(corpus_parts)
            )
        else:
            parts.append(
                "## EXISTING CORPUS DOCUMENTS\n(no active SOP/POLICY documents)"
            )

        parts.append(
            "## TASK\n"
            "Analyze the NEW DOCUMENT against each EXISTING CORPUS DOCUMENT "
            "for semantic contradictions. A contradiction exists when the new "
            "document and an existing document make statements that cannot both "
            "be true in the same context.\n\n"
            "Contradiction types:\n"
            "- direct_conflict: The documents make directly opposing factual claims "
            "(e.g. '7-day return window' vs '30-day return window').\n"
            "- scope_overlap: The documents cover the same scenario with different "
            "rules, creating ambiguity (e.g. two different escalation paths for the "
            "same condition).\n"
            "- temporal_conflict: The documents reference different time periods or "
            "versions of a policy in a conflicting way.\n\n"
            "Only flag genuine semantic contradictions. Different sections, "
            "complementary information, or different topics are NOT contradictions. "
            "If no contradictions exist, set has_contradiction=false and "
            "contradicting_documents=[].\n\n"
            f"Use the document ID from the corpus exactly: document_id must be "
            f"\"{new_doc_id}\"."
        )
        return "\n\n".join(parts)

    def parse_output(self, raw_text: str) -> dict[str, Any] | None:
        text = raw_text.strip()
        if text.startswith("```"):
            # Strip opening fence line (```json or ```)
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            # Strip everything from the first closing fence onward —
            # models sometimes append rationale text after the closing ```.
            if "```" in text:
                text = text[:text.index("```")].strip()

        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(parsed, dict):
            return None

        d: dict[str, Any] = cast("dict[str, Any]", parsed)

        if not isinstance(d.get("document_id"), str):
            return None

        has_contradiction: Any = d.get("has_contradiction")
        if not isinstance(has_contradiction, bool):
            return None

        contradicting: Any = d.get("contradicting_documents")
        if not isinstance(contradicting, list):
            d["contradicting_documents"] = []
        else:
            valid_types = {t.value for t in ContradictionType}
            cleaned: list[dict[str, Any]] = []
            for item in cast("list[Any]", contradicting):
                if not isinstance(item, dict):
                    continue
                item_d: dict[str, Any] = cast("dict[str, Any]", item)
                ctype: Any = item_d.get("contradiction_type", "")
                if ctype not in valid_types:
                    continue
                confidence: Any = item_d.get("confidence", 0.0)
                if not isinstance(confidence, (int, float)):
                    confidence = 0.0
                cleaned.append({
                    "doc_id": str(item_d.get("doc_id", "")),
                    "excerpt": str(item_d.get("excerpt", ""))[:500],
                    "contradicting_excerpt": str(item_d.get("contradicting_excerpt", ""))[:500],
                    "contradiction_type": ctype,
                    "confidence": max(0.0, min(1.0, float(confidence))),
                })
            d["contradicting_documents"] = cleaned

        if not has_contradiction:
            d["contradicting_documents"] = []

        return d

    def _check_money_goods(self, parsed: dict[str, Any]) -> bool:
        # Contradiction report output contains no money/goods commitments.
        return False


def safe_no_contradiction(document_id: str) -> dict[str, Any]:
    """Fail-open verdict when the agent is unavailable.

    Conservative: no contradiction flagged, document proceeds to normal
    PENDING_REVIEW. The injection scanner is the safety floor for KB quality.
    """
    return {
        "document_id": document_id,
        "has_contradiction": False,
        "contradicting_documents": [],
    }


def contradiction_report_to_quarantine_metadata(
    report: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract quarantine metadata from a ContradictionReport.

    Returns metadata dict (for review) if contradictions found, None otherwise.
    The KnowledgeRuntime uses this to decide whether to keep the document
    quarantined with contradiction_flagged reason.
    """
    if not report.get("has_contradiction", False):
        return None
    contradicting = report.get("contradicting_documents", [])
    if not contradicting:
        return None
    return {
        "contradiction_flagged": True,
        "contradiction_count": len(contradicting),
        "contradicting_doc_ids": [c["doc_id"] for c in contradicting],
        "highest_confidence": max(
            (c.get("confidence", 0.0) for c in contradicting), default=0.0
        ),
        "contradiction_types": list(
            {c["contradiction_type"] for c in contradicting}
        ),
    }
