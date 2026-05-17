"""Supervisor evaluators.

* `base`    — abstract `BaseEvaluator` contract.
* `registry`— `EvaluatorRegistry` with sorted-name iteration.
* `builtin` — four reference evaluators (completion, tool, governance,
              state-machine). Each is a focused inspection, never a
              catch-all "general health" check.
"""

from app.supervisor.evaluators.base import BaseEvaluator
from app.supervisor.evaluators.registry import EvaluatorRegistry

__all__ = ["BaseEvaluator", "EvaluatorRegistry"]
