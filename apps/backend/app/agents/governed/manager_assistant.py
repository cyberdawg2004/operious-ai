"""Manager Assistant Agent — Amazon-Q-style analytics assistant for tenant managers.

DESIGN: Query-templated (NOT text-to-SQL).

The LLM maps a natural-language question to ONE of a curated set of predefined,
tenant-scoped, parameterised query keys. The query runner fetches real data using
those pre-built queries (RLS-enforced). The LLM then narrates the result.

The LLM NEVER writes SQL or accesses data directly. If no query key matches, the
agent returns an honest "I can't answer that" rather than fabricating a number.

Safe-query catalog (SAFE_QUERIES):
  Each entry defines:
    - key: machine-readable identifier
    - label: human-readable name
    - description: what it answers
    - params: list of parameter names the query accepts
    - examples: sample natural-language phrasings

Two LLM passes:
  Pass 1 (intent mapping): question → {query_key, params, window_days}
  Pass 2 (narration):      query_key + result_data → conversational answer

Tenant isolation: every query is scoped to agent_input.tenant_id. The result
fetcher (ManagerQueryRunner) enforces tenant_id on every call — structurally
preventing cross-tenant data exposure.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, cast

from app.agents.governed.base import AgentInput, BaseGovernedLLMAgent
from app.agents.governed.policy import AgentPolicyRecord
from app.cognition.llm import DiagnosticLLMClient, DiagnosticLLMMessage
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.tenant.persistence import TenantConfigurationRepository
from app.types.json import JsonObject

logger = logging.getLogger(__name__)

MANAGER_ASSISTANT_POLICY_TYPE = "manager_assistant"


# ── Safe-query catalog ────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class SafeQueryDef:
    key: str
    label: str
    description: str
    params: tuple[str, ...]
    examples: tuple[str, ...]


SAFE_QUERIES: tuple[SafeQueryDef, ...] = (
    SafeQueryDef(
        key="auto_resolution_rate",
        label="Auto-resolution rate",
        description=(
            "Fraction of tickets auto-resolved by the agent without human "
            "intervention, over a time window."
        ),
        params=("window_days",),
        examples=(
            "what's my auto-resolution rate this week",
            "how many tickets did the agent resolve automatically",
            "what percentage of cases were handled without a human",
        ),
    ),
    SafeQueryDef(
        key="ticket_volume",
        label="Ticket volume",
        description="Total number of customer tickets / sessions processed over a time window.",
        params=("window_days",),
        examples=(
            "how many tickets did we get this week",
            "what's our ticket volume for the last 7 days",
            "how busy was support this month",
        ),
    ),
    SafeQueryDef(
        key="pending_action_approvals",
        label="Pending action approvals",
        description=(
            "Number of agent-proposed actions (e.g. refunds) currently waiting "
            "for human approval."
        ),
        params=(),
        examples=(
            "how many refunds are pending approval",
            "how many actions need my sign-off",
            "what's waiting for approval right now",
            "pending approvals count",
        ),
    ),
    SafeQueryDef(
        key="pending_case_approvals",
        label="Pending case approvals",
        description=(
            "Number of cases (SME-reviewed resolutions) currently pending human review."
        ),
        params=(),
        examples=(
            "how many cases are waiting for human review",
            "pending cases needing approval",
            "case approval queue depth",
        ),
    ),
    SafeQueryDef(
        key="escalation_rate",
        label="Escalation rate",
        description="Fraction of tickets that escalated to a human agent over a time window.",
        params=("window_days",),
        examples=(
            "what's my escalation rate",
            "how often do tickets escalate to humans",
            "what percentage of conversations needed a human",
        ),
    ),
    SafeQueryDef(
        key="governance_deny_rate",
        label="Governance deny rate",
        description=(
            "Fraction of agent decisions that were blocked/denied by the "
            "governance layer over a time window."
        ),
        params=("window_days",),
        examples=(
            "how often is the agent getting blocked by governance",
            "what's the governance deny rate",
            "what percentage of agent decisions were denied",
        ),
    ),
    SafeQueryDef(
        key="qa_score",
        label="Average QA score",
        description=(
            "Average quality-assurance score across agent responses "
            "over a time window."
        ),
        params=("window_days",),
        examples=(
            "what's the average quality score this week",
            "how is the agent performing on QA",
            "what are the QA scores looking like",
        ),
    ),
    SafeQueryDef(
        key="sop_conflicts",
        label="SOP / knowledge base conflicts",
        description=(
            "List of known semantic contradictions in the tenant's active "
            "knowledge base (SOPs that conflict with each other)."
        ),
        params=(),
        examples=(
            "which SOPs conflict",
            "are there any contradictions in my knowledge base",
            "what are the SOP conflicts",
            "which knowledge documents are contradicting each other",
        ),
    ),
    SafeQueryDef(
        key="open_escalations",
        label="Open escalations",
        description=(
            "Number and list of escalations currently open (pending human review)."
        ),
        params=(),
        examples=(
            "how many escalations are open right now",
            "show me the open escalations",
            "which escalations are still pending",
        ),
    ),
    SafeQueryDef(
        key="avg_response_latency",
        label="Average agent response latency",
        description="Average end-to-end latency (ms) for agent responses over a time window.",
        params=("window_days",),
        examples=(
            "how fast is the agent responding",
            "what's the average response time",
            "latency this week",
        ),
    ),
    SafeQueryDef(
        key="active_sessions",
        label="Active conversations",
        description="Number of currently active customer sessions / conversations.",
        params=(),
        examples=(
            "how many active conversations are there right now",
            "how many sessions are currently live",
            "active conversation count",
        ),
    ),
    SafeQueryDef(
        key="top_issue_categories",
        label="Top issue categories",
        description=(
            "Most common issue categories classified by the diagnostic agent "
            "over a time window."
        ),
        params=("window_days",),
        examples=(
            "what are the most common issues customers have",
            "what issues come up most",
            "top issue categories this week",
        ),
    ),
)

_QUERY_CATALOG_TEXT = "\n".join(
    f"- key={q.key!r}: {q.description} "
    f"(params: {list(q.params) or 'none'}; "
    f"examples: {'; '.join(q.examples[:2])})"
    for q in SAFE_QUERIES
)

_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["query_key", "window_days", "confidence", "cannot_answer"],
    "properties": {
        "query_key": {
            "type": "string",
            "description": "The key from the catalog, or empty string if cannot_answer=true.",
        },
        "window_days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 90,
            "description": "Time window in days. Use 7 for 'this week', 30 for 'this month'.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence that this query_key answers the question (0.0–1.0).",
        },
        "cannot_answer": {
            "type": "boolean",
            "description": "True if the question does not map to any query in the catalog.",
        },
    },
    "additionalProperties": False,
}

_NARRATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer", "chart_type", "chart_data"],
    "properties": {
        "answer": {
            "type": "string",
            "description": "Conversational answer narrating the data. 1-4 sentences.",
        },
        "chart_type": {
            "type": "string",
            "enum": ["none", "bar", "number"],
            "description": "Chart type: 'none' for prose-only, 'bar' for comparisons, 'number' for a single KPI.",
        },
        "chart_data": {
            "type": "object",
            "description": (
                "For chart_type='number': {value, label, unit}. "
                "For chart_type='bar': {labels: [...], values: [...], unit}. "
                "For chart_type='none': {}."
            ),
        },
    },
    "additionalProperties": False,
}

_VALID_QUERY_KEYS = frozenset(q.key for q in SAFE_QUERIES)


class ManagerAssistantAgent(BaseGovernedLLMAgent):
    """Governed LLM agent for natural-language analytics queries.

    Two-pass pipeline:
      1. Intent mapping: question → query_key + params
      2. Narration:      query result → conversational answer

    Skip money/goods check (read-only, no actions).
    Skip semantic drift check (internal analytics output, not customer-facing).
    """

    policy_type = MANAGER_ASSISTANT_POLICY_TYPE
    operational_act = OperationalAct.MANAGER_ASSISTANT_QUERY
    output_schema = _NARRATION_SCHEMA
    substrate = OperationalSubstrate.AGENTS

    max_output_tokens = 1024
    temperature = 0.0
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
        self._query_result: dict[str, Any] | None = None
        self._cannot_answer: bool = False
        self._cannot_answer_reason: str = ""
        self._matched_query_key: str = ""

    # ── Pass 1 helpers (called externally before run()) ──────────────────────

    async def map_intent(
        self,
        question: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Pass 1: map question → query_key + window_days.

        Returns parsed intent dict, or a cannot_answer dict on failure.
        """
        system = (
            "You are an intent mapper for a tenant operations assistant.\n"
            "Given a manager's question, identify which predefined query key "
            "from the catalog below best answers it. Never invent a key.\n\n"
            f"CATALOG:\n{_QUERY_CATALOG_TEXT}\n\n"
            f"OUTPUT SCHEMA:\n```json\n{json.dumps(_INTENT_SCHEMA, indent=2)}\n```\n\n"
            "Rules:\n"
            "- If the question maps to a catalog key with confidence >= 0.7, set "
            "  that key and cannot_answer=false.\n"
            "- If no key matches OR confidence < 0.7, set cannot_answer=true and "
            "  query_key='' — do NOT fabricate a key.\n"
            "- window_days: 7 for 'week/weekly', 30 for 'month/monthly', "
            "  1 for 'today', 90 for 'quarter'. Default 7.\n"
            "- Respond with valid JSON only. No prose before or after."
        )
        try:
            completion = await self._llm.complete(
                system_prompt=system,
                messages=(DiagnosticLLMMessage(role="user", content=question),),
                max_output_tokens=256,
                temperature=0.0,
                tenant_id=tenant_id,
            )
            return _parse_json_strict(completion.text) or {"cannot_answer": True}
        except Exception:
            logger.warning("manager_assistant_intent_mapping_failed tenant=%s", tenant_id)
            return {"cannot_answer": True}

    # ── Override: build_user_content is Pass 2 (narration) ──────────────────

    def build_user_content(
        self, agent_input: AgentInput, policy: AgentPolicyRecord
    ) -> str:
        """Build the narration prompt from the pre-fetched query result."""
        question = str(agent_input.content.get("question", ""))
        query_key = str(agent_input.content.get("query_key", ""))
        query_result = agent_input.content.get("query_result", {})
        query_label = next(
            (q.label for q in SAFE_QUERIES if q.key == query_key), query_key
        )
        return (
            f"Manager question: {question}\n\n"
            f"Query run: {query_label}\n\n"
            f"Raw data from the tenant's system:\n"
            f"```json\n{json.dumps(query_result, indent=2, default=str)}\n```\n\n"
            "Task: Write a short, conversational answer (1-4 sentences) narrating "
            "the above data. Include a chart if the data is quantitative and a chart "
            "would help. Be factual — only state what the numbers show."
        )

    def parse_output(self, raw_text: str) -> dict[str, Any] | None:
        parsed = _parse_json_strict(raw_text)
        if parsed is None:
            return None
        if not isinstance(parsed.get("answer"), str):
            return None
        chart_type = parsed.get("chart_type", "none")
        if chart_type not in {"none", "bar", "number"}:
            parsed["chart_type"] = "none"
        if not isinstance(parsed.get("chart_data"), dict):
            parsed["chart_data"] = {}
        return parsed

    def _check_money_goods(self, parsed: dict[str, Any]) -> bool:
        # Read-only analytics — never has money/goods commitments.
        return False


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_json_strict(raw: str) -> JsonObject | None:
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if "```" in text:
            text = text[: text.index("```")].strip()
    # Try direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return cast(JsonObject, obj)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try extracting first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                return cast(JsonObject, obj)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ── Cannot-answer response builder ───────────────────────────────────────────

def cannot_answer_response(question: str) -> dict[str, Any]:
    """Return a helpful 'I can't answer that' response with the catalog list."""
    catalog_lines = "\n".join(f"• {q.label}: {q.description}" for q in SAFE_QUERIES)
    return {
        "answer": (
            f"I don't have a query for that question. "
            f"Here's what I can tell you about your operation:\n{catalog_lines}"
        ),
        "chart_type": "none",
        "chart_data": {},
        "cannot_answer": True,
    }


__all__ = [
    "MANAGER_ASSISTANT_POLICY_TYPE",
    "SAFE_QUERIES",
    "SafeQueryDef",
    "ManagerAssistantAgent",
    "cannot_answer_response",
]
