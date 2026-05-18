"""Operational act catalog — closed institutional vocabulary (P2-B).

Each value names ONE operational act that requires capability
legality. Orchestration runtimes MUST import from this catalog
rather than passing free-form strings; doing so prevents the
distributed-policy-chaos failure mode where two callers spell the
"same" act differently and develop divergent legality semantics.

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
    """Closed catalog of operational acts subject to capability legality.

    The enum value is BOTH the canonical ``action`` string on the
    :class:`GovernanceContext` and the ``required_capability`` on the
    :class:`CapabilityGovernanceSubject`. Keeping the two aligned
    eliminates a translation layer that historically produces drift.
    """

    # ─── arbitration ────────────────────────────────────────────────
    ARBITRATION_EVALUATE = "arbitration:evaluate"

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

    # ─── hardening ──────────────────────────────────────────────────
    HARDENING_RECORD_FAILURE = "hardening:record_failure"

    # ─── organizational intelligence ────────────────────────────────
    OI_COMMUNICATION_REGISTER = "oi_communication:register"
    OI_COMMUNICATION_RETRIEVE = "oi_communication:retrieve"
    OI_MEMORY_LIST = "oi_memory:list"
    OI_MEMORY_PROPOSE = "oi_memory:propose"
    OI_RECOMMENDATION_GENERATE = "oi_recommendation:generate"
    OI_SOP_INGEST = "oi_sop:ingest"
    OI_TONALITY_CLASSIFY = "oi_tonality:classify"

    # ─── session ────────────────────────────────────────────────────
    SESSION_OPEN = "session:open"

    # ─── supervisor ─────────────────────────────────────────────────
    SUPERVISOR_INSPECT = "supervisor:inspect"


__all__ = ["OperationalAct"]
