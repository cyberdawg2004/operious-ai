"""Base governance subject + discriminator enum + legacy fallback.

Architectural note: subjects are deliberately **not** built via
dataclass inheritance — `@dataclass(frozen=True, slots=True)`
combined with parent-default fields runs into Python's
"defaulted-fields-must-come-last" constraint when subclasses add
required typed fields. Instead, every typed subject is its own
standalone frozen dataclass that inherits a tiny marker class
`BaseGovernanceSubject`. The marker contributes empty slots and a
shared `to_dict` contract; each concrete subject sets its own `kind`
default.

This trade keeps each subject:
* fully typed with its own ordered field list,
* unambiguous in IDE / mypy inspection,
* deterministically serializable via the per-class `to_dict`,
without paying the inheritance-defaults tax.

`GenericGovernanceSubject` is the legacy fallback used only during
the migration window — new code MUST use a typed subject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from app.types.json import JsonObject


def _empty_json_object() -> JsonObject:
    return {}


def _empty_opaque_mapping() -> dict[str, Any]:
    return {}


class SubjectKind(StrEnum):
    """Discriminator vocabulary for typed governance subjects.

    Adding a new subject kind:
        1. Add a value here.
        2. Create the subject dataclass under `app/governance/subjects/`.
        3. Set `kind: SubjectKind = SubjectKind.NEW_VALUE` as the
           default on the new dataclass — callers never set `kind`
           directly.
        4. (Optional) Add factories in `factories.py`.
        5. Policies that handle it declare it in
           `applicable_subject_kinds`.

    The vocabulary is a closed set; downstream consumers (persistence,
    audit) MUST treat an unknown kind as fail-safe (deny / log).
    """

    GENERIC = "generic"
    RETRIEVAL = "retrieval"
    EXECUTION = "execution"
    AGENT_ACTION = "agent_action"
    MANAGER_APPROVAL = "manager_approval"
    COMMUNICATION = "communication"
    CAPABILITY = "capability"


class BaseGovernanceSubject:
    """Marker base for every typed governance subject.

    Holds no instance state. Concrete subjects are standalone frozen
    dataclasses inheriting from this — see module docstring for
    rationale. The two attributes declared here are TYPE HINTS only;
    they document the contract every subclass dataclass must satisfy.
    """

    __slots__ = ()

    # Contract — every concrete subject defines these as dataclass fields.
    kind: SubjectKind
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, replay-safe serialization.

        Concrete subjects MUST override. The dict shape is what the
        persistence layer stores and what audit + supervisor runtimes
        read; treat it as a stable contract.
        """
        raise NotImplementedError(
            "BaseGovernanceSubject is a marker; subclasses must override to_dict()"
        )


@dataclass(frozen=True, slots=True)
class GenericGovernanceSubject(BaseGovernanceSubject):
    """Legacy fallback subject for the migration window.

    Carries opaque key/value data in `data`. **New code MUST NOT use
    this** — create a typed subject under `app/governance/subjects/`
    instead. The substrate keeps it so test fixtures that don't need
    typed semantics (decision-builder unit tests, abstract chain
    tests) keep working through the migration.

    Audit / persistence will record `kind="generic"` for these
    subjects — supervisor runtimes use that as the explicit signal
    that a request was governed under a legacy path.
    """

    data: Mapping[str, Any] = field(default_factory=_empty_opaque_mapping)
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_object)
    kind: SubjectKind = SubjectKind.GENERIC

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "metadata": dict(self.metadata),
            "data": dict(self.data),
        }


__all__ = [
    "SubjectKind",
    "BaseGovernanceSubject",
    "GenericGovernanceSubject",
]
