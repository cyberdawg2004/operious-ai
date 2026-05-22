"""Built-in supervisor evaluators.

Four focused inspections:

* `execution_completion` — terminal state vs. agent error.
* `tool_invocation`      — tool outcome hygiene (denied / failed).
* `governance_compliance`— governance non-allow decisions.
* `state_machine_health` — illegal-transition detection.

Each is a separate class so individual evaluators can be enabled /
disabled by configuration without touching others.
"""

from app.supervisor.evaluators.builtin.execution_completion import (
    ExecutionCompletionEvaluator,
)
from app.supervisor.evaluators.builtin.governance_compliance import (
    GovernanceComplianceEvaluator,
)
from app.supervisor.evaluators.builtin.state_machine_health import (
    StateMachineHealthEvaluator,
)
from app.supervisor.evaluators.builtin.tool_invocation import (
    ToolInvocationEvaluator,
)
from app.supervisor.evaluators.registry import EvaluatorRegistry


def build_default_evaluator_registry() -> EvaluatorRegistry:
    """Build the default supervisor evaluator registry."""
    registry = EvaluatorRegistry()
    registry.register(ExecutionCompletionEvaluator())
    registry.register(ToolInvocationEvaluator())
    registry.register(GovernanceComplianceEvaluator())
    registry.register(StateMachineHealthEvaluator())
    return registry

__all__ = [
    "build_default_evaluator_registry",
    "ExecutionCompletionEvaluator",
    "ToolInvocationEvaluator",
    "GovernanceComplianceEvaluator",
    "StateMachineHealthEvaluator",
]
