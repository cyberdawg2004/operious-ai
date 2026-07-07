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
import re
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
        # Set by build_user_content; consumed by parse_output attribution backstop.
        self._anchor_text: str = ""
        self._corpus_texts: dict[str, str] = {}

    def build_user_content(
        self, agent_input: AgentInput, policy: AgentPolicyRecord
    ) -> str:
        content = agent_input.content
        new_doc_id = content.get("new_document_id", "")
        new_doc_title = content.get("new_document_title", "")
        new_doc_type = content.get("new_document_type", "")
        new_doc_content = content.get("new_document_content", "")
        corpus_documents = content.get("corpus_documents", [])

        # Store for attribution backstop in parse_output.
        self._anchor_text = str(new_doc_content)
        self._corpus_texts = {
            str(cast("dict[str, Any]", d).get("doc_id", "")): str(
                cast("dict[str, Any]", d).get("content", "")
            )
            for d in cast("list[Any]", corpus_documents)
        }

        if len(new_doc_content) > _MAX_DOCUMENT_CHARS:
            new_doc_content = new_doc_content[:_MAX_DOCUMENT_CHARS] + "\n[truncated]"

        parts = [
            f"## NEW DOCUMENT (anchor — ID: {new_doc_id})\n"
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
                    f"### CORPUS DOC [{doc_id}] {doc_title}\n{doc_content}"
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
            f"Compare the NEW DOCUMENT (anchor, ID: \"{new_doc_id}\") against each "
            "CORPUS DOCUMENT for semantic contradictions.\n\n"
            "A contradiction requires ALL of the following to be true:\n"
            "  (a) Both documents address the EXACT SAME subject and triggering condition.\n"
            "  (b) They give CONFLICTING rules — a customer or agent following BOTH rules "
            "simultaneously would face an impossible situation.\n"
            "  (c) The conflict is DIRECTLY stated in the anchor document's own text.\n\n"
            "SAME-SUBJECT TEST: Before flagging, ask: 'Would a customer/agent facing THIS "
            "specific situation consult BOTH of these documents?' If not, they cover "
            "different topics and there is no contradiction.\n\n"
            "REQUIRED: For each pair you compare, answer this question explicitly:\n"
            "  Q: What is the exact question/scenario both statements answer?\n"
            "  If the two statements answer DIFFERENT questions → no contradiction.\n\n"
            "Common non-contradiction patterns (different questions → NOT a contradiction):\n"
            "  - Return window deadline vs warranty coverage period: different triggers "
            "(voluntary return vs manufacturing defect).\n"
            "  - Refund processing timeline vs approval authority threshold: different "
            "questions (when does money move vs who can authorize).\n"
            "  - Carrier undeliverable-package window vs customer return window: different "
            "events (carrier sends back vs customer decides to return).\n"
            "  - Payment-failure hold procedure vs escalation threshold for refunds: "
            "different domains (incoming payment vs outgoing refund).\n"
            "  - Warranty repair outcome vs customer refund process: different triggers.\n\n"
            "Real contradiction examples (same question, conflicting answers):\n"
            "  - 'Returns accepted within 30 days' vs 'Returns must be initiated within "
            "14 days': same question (return deadline), conflicting answers → contradiction.\n"
            "  - 'Agents may authorize up to $200' vs 'Agent limit is $150': same question "
            "(agent authority threshold), conflicting answers → contradiction.\n\n"
            "EXCERPT ATTRIBUTION RULE:\n"
            "  - `excerpt` = verbatim text from the NEW DOCUMENT (anchor) above.\n"
            "  - `contradicting_excerpt` = verbatim text from the specific CORPUS DOCUMENT.\n"
            "  - If the conflicting statement is not in the anchor's own text → no flag.\n\n"
            "Contradiction types:\n"
            "  - direct_conflict: Same question, directly opposing factual claims.\n"
            "  - scope_overlap: Same scenario/trigger, different rules, creating ambiguity.\n"
            "  - temporal_conflict: Same policy, conflicting time periods or versions.\n\n"
            "If no genuine same-question contradictions exist, set has_contradiction=false "
            "and contradicting_documents=[].\n\n"
            f"document_id MUST be exactly: \"{new_doc_id}\"."
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
                confidence_f = max(0.0, min(1.0, float(confidence)))
                excerpt_a = str(item_d.get("excerpt", ""))[:500]
                excerpt_b = str(item_d.get("contradicting_excerpt", ""))[:500]
                corpus_doc_id = str(item_d.get("doc_id", ""))

                # ── Confidence floor backstop ─────────────────────────────
                # Drop items below the minimum confidence threshold even if
                # the prompt already requests >= 0.93 — defense-in-depth.
                if confidence_f < _MIN_CONFIDENCE:
                    logger.debug(
                        "contradiction_confidence_drop corpus_doc=%s confidence=%.2f",
                        corpus_doc_id, confidence_f,
                    )
                    continue

                # ── Attribution backstop (defense-in-depth) ──────────────
                # Verify excerpt_a appears in the anchor doc and excerpt_b
                # appears in the specific corpus doc being compared. If
                # either is a misattribution (quoting text from a third
                # doc), drop this contradiction — it's a phantom conflict.
                # Skip backstop when anchor text is not yet set (parse_output
                # called without build_user_content — e.g. in unit tests that
                # exercise the parser in isolation).
                if self._anchor_text and not _excerpt_present(excerpt_a, self._anchor_text):
                    logger.debug(
                        "contradiction_attribution_drop anchor_mismatch "
                        "corpus_doc=%s excerpt=%r",
                        corpus_doc_id, excerpt_a[:80],
                    )
                    continue
                corpus_text = self._corpus_texts.get(corpus_doc_id, "")
                if corpus_text and not _excerpt_present(excerpt_b, corpus_text):
                    logger.debug(
                        "contradiction_attribution_drop corpus_mismatch "
                        "corpus_doc=%s excerpt=%r",
                        corpus_doc_id, excerpt_b[:80],
                    )
                    continue

                cleaned.append({
                    "doc_id": corpus_doc_id,
                    "excerpt": excerpt_a,
                    "contradicting_excerpt": excerpt_b,
                    "contradiction_type": ctype,
                    "confidence": confidence_f,
                })
            d["contradicting_documents"] = cleaned

        if not has_contradiction:
            d["contradicting_documents"] = []
        elif not d["contradicting_documents"]:
            # All items failed attribution backstop — treat as no contradiction.
            d["has_contradiction"] = False

        return d

    def _check_money_goods(self, parsed: dict[str, Any]) -> bool:
        # Contradiction report output contains no money/goods commitments.
        return False


_MIN_EXCERPT_LEN = 15
_EXCERPT_MATCH_THRESHOLD = 0.75  # fraction of words that must appear in source
_MIN_CONFIDENCE = 0.93  # backstop: drop any item below this even if prompt allows higher


def _excerpt_present(excerpt: str, source_text: str) -> bool:
    """Return True if excerpt plausibly belongs to source_text.

    Uses two checks (either suffices):
    1. Verbatim substring (case-folded, collapsing whitespace) — the gold
       standard; catches exact quotes.
    2. Word-overlap fallback — catches minor truncation / ellipsis by the
       model where the words are right but spacing slightly differs.

    Short excerpts (< _MIN_EXCERPT_LEN chars) pass unconditionally — they're
    too short to distinguish and are harmless to admit.
    """
    if len(excerpt.strip()) < _MIN_EXCERPT_LEN:
        return True

    # Normalise: collapse whitespace, case-fold.
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    norm_excerpt = _norm(excerpt)
    norm_source = _norm(source_text)

    # Check 1: verbatim substring.
    if norm_excerpt in norm_source:
        return True

    # Check 2: leading-phrase substring (first 40 chars of excerpt in source).
    # Handles cases where the model truncated at the 500-char limit mid-sentence.
    lead = norm_excerpt[:40]
    if len(lead) >= _MIN_EXCERPT_LEN and lead in norm_source:
        return True

    # Check 3: word-overlap — robust to minor whitespace/punctuation divergence.
    excerpt_words = set(re.findall(r"\b\w{4,}\b", norm_excerpt))
    if not excerpt_words:
        return True
    source_words = set(re.findall(r"\b\w{4,}\b", norm_source))
    overlap = len(excerpt_words & source_words) / len(excerpt_words)
    return overlap >= _EXCERPT_MATCH_THRESHOLD


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
