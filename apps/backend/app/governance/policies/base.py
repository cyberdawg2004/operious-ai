"""Policy contract.

Every governance policy implements this. The contract is minimal —
async `evaluate()` returning a sequence of rule-level results — which
keeps the engine able to treat every policy uniformly.

Subclassing rules:

* declare `name` — stable identifier, used by the registry;
* declare `supported_stages` — frozenset of `EnforcementStage`s; the
  chain validates this at composition time;
* declare `applicable_subject_kinds` — frozenset of `SubjectKind`s;
  the engine routes around policies whose declared subjects don't
  match the evaluation's `subject.kind`. **Empty frozenset means
  "applies to every subject kind"** — preserved for policies that
  are subject-kind-agnostic;
* implement `evaluate()` and return ONE `PolicyEvaluationResult` per
  rule. Never raise for normal "rule failed" outcomes; raise only on
  internal errors — the engine folds those into a synthetic DENY.

Applicability semantics (Sprint I Hardening):

A policy whose `applicable_subject_kinds` is non-empty and does NOT
include the evaluation's `subject.kind` is **skipped** by the engine.
A `"skipped"` `PolicyEvaluationTrace` is emitted but NO
`PolicyEvaluationResult` is produced — the policy is silent for this
evaluation. This is deterministic (pure function of policy + kind),
replay-safe (stable across runs), and what makes typed-subject
dispatch clean.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, FrozenSet, Sequence

from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enums import EnforcementStage
from app.governance.subjects.base import SubjectKind


class BaseGovernancePolicy(ABC):
    """Abstract base for every governance policy."""

    name: ClassVar[str] = ""
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset()
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset()
    """Subject kinds this policy handles.

    Empty frozenset (default) means "applies to every subject kind"
    — preserved as a compatible default for policies that don't care
    about subject typing. Concrete policies that read typed fields
    MUST narrow this to their expected kinds.
    """

    def supports(self, stage: EnforcementStage) -> bool:
        return stage in self.supported_stages

    def applies_to(self, kind: SubjectKind) -> bool:
        """True if this policy should be invoked for `kind`.

        Empty `applicable_subject_kinds` is treated as "any" — see
        class docstring.
        """
        if not self.applicable_subject_kinds:
            return True
        return kind in self.applicable_subject_kinds

    @abstractmethod
    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        """Return one result per rule evaluated by this policy.

        The engine guarantees `context.subject` is of an applicable
        kind when this is invoked — type-narrow accordingly.
        """


__all__ = ["BaseGovernancePolicy"]
