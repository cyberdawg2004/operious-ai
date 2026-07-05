"""MVP-3 — Fraud Detection Agent.

Instantiation of BaseGovernedLLMAgent that detects behavioral fraud
patterns beyond keyword matching. Runs on every ticket AFTER the
existing keyword gate. Configured entirely by tenant fraud policy —
no hardcoded vertical logic.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import Any, Mapping

from app.agents.governed.base import AgentInput, BaseGovernedLLMAgent
from app.agents.governed.policy import AgentPolicyRecord
from app.cognition.llm import DiagnosticLLMClient
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.tenant.persistence import TenantConfigurationRepository

logger = logging.getLogger(__name__)

FRAUD_DETECTION_POLICY_TYPE = "fraud_detection"


class FraudSignalKind(StrEnum):
    """Recognized fraud signal categories."""

    VELOCITY = "velocity"
    FIELD_INCONSISTENCY = "field_inconsistency"
    VALUE_ANOMALY = "value_anomaly"
    CLAIM_STACKING = "claim_stacking"
    IDENTITY_MISMATCH = "identity_mismatch"
    AGENT_UNAVAILABLE = "agent_unavailable"


FRAUD_SIGNAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ticket_id", "risk_score", "signal_kinds", "confidence", "reasoning"],
    "properties": {
        "ticket_id": {"type": "string"},
        "risk_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "signal_kinds": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [kind.value for kind in FraudSignalKind],
            },
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 500},
    },
    "additionalProperties": False,
}

_DEFAULT_THRESHOLD_LOW = 0.15
_DEFAULT_THRESHOLD_HIGH = 0.60


class FraudDetectionAgent(BaseGovernedLLMAgent):
    """Governed LLM agent for behavioral fraud detection.

    Runs inline in _evaluate_gate() after keyword checks. If the agent
    is unavailable or errors, returns risk_score=0.0 (conservative
    fail-open for the ENHANCEMENT — the keyword gate is the safety floor).
    """

    policy_type = FRAUD_DETECTION_POLICY_TYPE
    operational_act = OperationalAct.FRAUD_SIGNAL
    output_schema = FRAUD_SIGNAL_SCHEMA
    substrate = OperationalSubstrate.AGENTS

    max_output_tokens = 1024
    temperature = 0.0
    governance_authorized_terms = frozenset({"fraud", "refund", "credit"})
    # Observational agent: structured JSON output never shown to customers.
    # Semantic drift checking is designed for customer-facing reply text.
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
        ticket_text = content.get("ticket_text", "")
        extracted_fields = content.get("extracted_fields", {})
        customer_history = content.get("customer_history", {})
        session_id = agent_input.session_id

        fraud_config = policy.configuration.get("fraud_config", {})
        velocity_thresholds = fraud_config.get("velocity_thresholds", {})
        suspicious_patterns = fraud_config.get("suspicious_patterns", [])

        parts = [
            f"## TICKET\nSession: {session_id}\n\n{ticket_text}",
        ]
        if extracted_fields:
            parts.append(
                f"## EXTRACTED FIELDS\n```json\n{json.dumps(extracted_fields, indent=2)}\n```"
            )
        if customer_history:
            parts.append(
                f"## CUSTOMER HISTORY\n```json\n{json.dumps(customer_history, indent=2)}\n```"
            )
        if velocity_thresholds or suspicious_patterns:
            tenant_config = {}
            if velocity_thresholds:
                tenant_config["velocity_thresholds"] = velocity_thresholds
            if suspicious_patterns:
                tenant_config["suspicious_patterns"] = suspicious_patterns
            parts.append(
                f"## TENANT FRAUD CONFIGURATION\n```json\n{json.dumps(tenant_config, indent=2)}\n```"
            )

        parts.append(
            "## TASK\n"
            "Analyze the ticket for behavioral fraud signals. Consider:\n"
            "- Request velocity (multiple claims in short period)\n"
            "- Field inconsistency (conflicting information)\n"
            "- Value anomaly (claimed vs expected value mismatch)\n"
            "- Claim stacking (multiple claims on same item)\n"
            "- Identity mismatch (contact details inconsistent with account)\n\n"
            "Respond with the JSON schema provided. "
            "risk_score 0.0 means no signal, 1.0 means high-confidence fraud."
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

        risk_score = parsed.get("risk_score")
        if not isinstance(risk_score, (int, float)):
            return None
        parsed["risk_score"] = max(0.0, min(1.0, float(risk_score)))

        confidence = parsed.get("confidence")
        if not isinstance(confidence, (int, float)):
            parsed["confidence"] = parsed["risk_score"]
        else:
            parsed["confidence"] = max(0.0, min(1.0, float(confidence)))

        signal_kinds = parsed.get("signal_kinds")
        if not isinstance(signal_kinds, list):
            parsed["signal_kinds"] = []
        else:
            valid_kinds = {k.value for k in FraudSignalKind}
            parsed["signal_kinds"] = [
                k for k in signal_kinds if isinstance(k, str) and k in valid_kinds
            ]

        if not isinstance(parsed.get("ticket_id"), str):
            parsed["ticket_id"] = ""

        reasoning = parsed.get("reasoning")
        if not isinstance(reasoning, str):
            parsed["reasoning"] = ""
        elif len(reasoning) > 500:
            parsed["reasoning"] = reasoning[:500]

        return parsed

    def _check_money_goods(self, parsed: dict[str, Any]) -> bool:
        # Fraud signal output never contains money/goods commitments.
        # The fraud agent OBSERVES — it never proposes actions.
        return False


def resolve_fraud_thresholds(
    policy: AgentPolicyRecord | None,
) -> tuple[float, float]:
    """Extract (threshold_low, threshold_high) from agent policy config."""
    if policy is None:
        return (_DEFAULT_THRESHOLD_LOW, _DEFAULT_THRESHOLD_HIGH)
    fraud_config = policy.configuration.get("fraud_config", {})
    if not isinstance(fraud_config, dict):
        return (_DEFAULT_THRESHOLD_LOW, _DEFAULT_THRESHOLD_HIGH)
    low = fraud_config.get("threshold_low", _DEFAULT_THRESHOLD_LOW)
    high = fraud_config.get("threshold_high", _DEFAULT_THRESHOLD_HIGH)
    if not isinstance(low, (int, float)):
        low = _DEFAULT_THRESHOLD_LOW
    if not isinstance(high, (int, float)):
        high = _DEFAULT_THRESHOLD_HIGH
    return (float(low), float(high))


def fraud_signal_to_gate_reasons(
    signal: Mapping[str, Any],
    threshold_low: float,
    threshold_high: float,
) -> tuple[str, ...]:
    """Convert a FraudSignal output into gate reasons for _evaluate_gate().

    Returns empty tuple if risk_score < threshold_low.
    """
    risk_score = signal.get("risk_score", 0.0)
    if not isinstance(risk_score, (int, float)):
        return ()
    if risk_score < threshold_low:
        return ()
    if risk_score >= threshold_high:
        return ("fraud_risk_high",)
    return ("fraud_risk",)


def safe_fraud_signal() -> dict[str, Any]:
    """Return the fail-open signal when the agent is unavailable.

    Conservative: risk_score=0.0, the keyword gate remains the safety floor.
    """
    return {
        "ticket_id": "",
        "risk_score": 0.0,
        "signal_kinds": [FraudSignalKind.AGENT_UNAVAILABLE.value],
        "confidence": 0.0,
        "reasoning": "Fraud detection agent unavailable; keyword gate operational.",
    }
