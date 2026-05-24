"""Operational act catalog — closed institutional vocabulary.

Each value names ONE operational act that can appear in governance,
event-fabric, or replay chronology. Orchestration runtimes MUST
import from this catalog rather than passing free-form strings; doing
so prevents the distributed-policy-chaos failure mode where two callers
spell the "same" act differently and develop divergent semantics.

Not every operational act is capability-governed. Phase 2-C separates
the broad event ontology from the narrower capability-legality subset:
``CAPABILITY_GOVERNED_ACTS`` is the set that runtime entry points must
gate. Projected chronology acts may exist only to name replay facts.

Format invariant
────────────────
Every value is ``"<substrate>:<verb>"``. The colon is the only
separator. Both halves are lowercase snake_case. No bare keywords
(``"admin"``, ``"root"``), no bypass tokens (``"skip_rbac"``,
``"override"``), no environment suffixes (``"…:dev"``,
``"…:staging"``).

Adding a new act
────────────────
1. Add the enum value below with a stable ``<substrate>:<verb>``
   string.
2. Document the operational act it names in a one-line comment.
3. Update governance policy fixtures that need the new capability
   (the capability string is the same as the act string).
4. The catalog is closed — third-party / orchestration-local act
   strings are constitutionally rejected. There is no
   ``OperationalAct.OTHER`` and there is no string fallback.
"""

from __future__ import annotations

from enum import StrEnum


class OperationalAct(StrEnum):
    """Closed catalog of operational acts.

    When an act is present in :data:`CAPABILITY_GOVERNED_ACTS`, its
    enum value is BOTH the canonical ``action`` string on the
    :class:`GovernanceContext` and the ``required_capability`` on
    the :class:`CapabilityGovernanceSubject`. Keeping the two aligned
    for governed acts eliminates a translation layer that historically
    produces drift.
    """

    # ─── arbitration ────────────────────────────────────────────────
    ARBITRATION_EVALUATE = "arbitration:evaluate"

    # ─── boundary chronology projection ─────────────────────────────
    BOUNDARY_INGEST = "boundary:ingest"

    # ─── boundary (translation) ─────────────────────────────────────
    BOUNDARY_TRANSLATION_INGRESS = "boundary_translation:ingress"
    BOUNDARY_TRANSLATION_EGRESS = "boundary_translation:egress"

    # ─── boundary (voice) ───────────────────────────────────────────
    BOUNDARY_VOICE_INGRESS = "boundary_voice:ingress"
    BOUNDARY_VOICE_EGRESS = "boundary_voice:egress"

    # ─── coordination ───────────────────────────────────────────────
    COORDINATION_DISPATCH = "coordination:dispatch"
    COORDINATION_POLICY_EVALUATE = "coordination_policy:evaluate"
    COORDINATION_TOPOLOGY_EVALUATE = "coordination_topology:evaluate"

    # ─── governance chronology projection ───────────────────────────
    GOVERNANCE_DECIDE = "governance:decide"

    # ─── execution chronology projection ────────────────────────────
    EXECUTION_REQUEST = "execution:request"
    EXECUTION_OUTBOX_CREATE = "execution:outbox_create"
    EXECUTION_OUTBOX_CLAIM = "execution:outbox_claim"
    EXECUTION_OUTBOX_PUBLISH = "execution:outbox_publish"
    EXECUTION_OUTBOX_FAIL = "execution:outbox_fail"
    EXECUTION_CLAIM = "execution:claim"
    EXECUTION_COMPLETE = "execution:complete"
    EXECUTION_FAIL = "execution:fail"
    EXECUTION_RECOVER = "execution:recover"
    EXECUTION_DEAD_LETTER = "execution:dead_letter"

    # ─── escalation chronology projection ───────────────────────────
    ESCALATION_CREATE = "escalation:create"
    ESCALATION_REVIEW = "escalation:review"
    ESCALATION_APPROVE = "escalation:approve"
    ESCALATION_REJECT = "escalation:reject"

    # ─── hardening ──────────────────────────────────────────────────
    HARDENING_RECORD_FAILURE = "hardening:record_failure"

    # ─── organizational intelligence ────────────────────────────────
    OI_COMMUNICATION_REGISTER = "oi_communication:register"
    OI_COMMUNICATION_RETRIEVE = "oi_communication:retrieve"
    OI_MEMORY_LIST = "oi_memory:list"
    OI_MEMORY_PROPOSE = "oi_memory:propose"
    OI_RECOMMENDATION_GENERATE = "oi_recommendation:generate"
    OI_SOP_INGEST = "oi_sop:ingest"
    OI_SOP_APPROVAL_PROPOSE = "oi_sop:approval_propose"
    OI_SOP_APPROVAL_APPROVE = "oi_sop:approval_approve"
    OI_SOP_APPROVAL_REJECT = "oi_sop:approval_reject"
    OI_SOP_APPROVAL_APPLY = "oi_sop:approval_apply"
    OI_TONALITY_CLASSIFY = "oi_tonality:classify"

    # ─── QA chronology projection ───────────────────────────────────
    QA_SCORE = "qa:score"

    # ─── session ────────────────────────────────────────────────────
    SESSION_OPEN = "session:open"
    SESSION_ATTACH_CONTEXT = "session:attach_context"
    SESSION_RECORD_CORRELATION = "session:record_correlation"
    SESSION_LINK_LINEAGE = "session:link_lineage"
    SESSION_RECLASSIFY_LIFECYCLE = "session:reclassify_lifecycle"
    SESSION_RECORD_DORMANCY = "session:record_dormancy"
    SESSION_RECORD_RESUMPTION = "session:record_resumption"
    SESSION_RECORD_TERMINATION = "session:record_termination"
    SESSION_RECORD_ARCHIVAL = "session:record_archival"
    SESSION_OBSERVE_OPERATION = "session:observe_operation"

    # ─── supervisor ─────────────────────────────────────────────────
    SUPERVISOR_INSPECT = "supervisor:inspect"


CAPABILITY_GOVERNED_ACTS: frozenset[OperationalAct] = frozenset(
    {
        OperationalAct.ARBITRATION_EVALUATE,
        OperationalAct.BOUNDARY_TRANSLATION_INGRESS,
        OperationalAct.BOUNDARY_TRANSLATION_EGRESS,
        OperationalAct.BOUNDARY_VOICE_INGRESS,
        OperationalAct.BOUNDARY_VOICE_EGRESS,
        OperationalAct.COORDINATION_DISPATCH,
        OperationalAct.COORDINATION_POLICY_EVALUATE,
        OperationalAct.COORDINATION_TOPOLOGY_EVALUATE,
        OperationalAct.HARDENING_RECORD_FAILURE,
        OperationalAct.OI_COMMUNICATION_REGISTER,
        OperationalAct.OI_COMMUNICATION_RETRIEVE,
        OperationalAct.OI_MEMORY_LIST,
        OperationalAct.OI_MEMORY_PROPOSE,
        OperationalAct.OI_RECOMMENDATION_GENERATE,
        OperationalAct.OI_SOP_INGEST,
        OperationalAct.OI_TONALITY_CLASSIFY,
        OperationalAct.SESSION_OPEN,
        OperationalAct.SUPERVISOR_INSPECT,
    }
)


__all__ = ["CAPABILITY_GOVERNED_ACTS", "OperationalAct"]
