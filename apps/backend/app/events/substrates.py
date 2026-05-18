"""Operational substrate catalog (P2-D).

Closed vocabulary of organizational substrates that can emit
:class:`OperationalEvent` instances. Distinct from
:class:`app.hardening.enums.SubstrateName` (which models hardening's
ownership boundaries and historically omits HARDENING itself); this
catalog is complete and authoritative for the event fabric.

A bijection invariant (``test_operational_event_fabric.py``) pins
that every value in hardening's substrate enum also appears here,
preventing silent drift between the two catalogs.

Adding a new substrate:
    1. Add a value here with a stable snake_case identifier.
    2. Confirm the catalog still passes the hardening-bijection test.
    3. If the new substrate also has hardening-tracked ownership
       boundaries, add it to :class:`app.hardening.enums.SubstrateName`
       too.
"""

from __future__ import annotations

from enum import StrEnum


class OperationalSubstrate(StrEnum):
    """Closed catalog of operational substrates."""

    AGENTS = "agents"
    ARBITRATION = "arbitration"
    BOUNDARY = "boundary"
    BOUNDARY_TRANSLATION = "boundary_translation"
    BOUNDARY_VOICE = "boundary_voice"
    COORDINATION = "coordination"
    COORDINATION_POLICY = "coordination_policy"
    COORDINATION_TOPOLOGY = "coordination_topology"
    GOVERNANCE = "governance"
    HARDENING = "hardening"
    HUMAN = "human"
    MEMORY = "memory"
    # Coarse OI parent + fine OI sub-substrates. The fine entries
    # exist because the OI sub-domains (sop / tonality / communication
    # / memory artifacts / recommendations) emit events independently
    # — stamping the coarse parent would lose attribution fidelity.
    ORGANIZATIONAL_INTELLIGENCE = "organizational_intelligence"
    OI_COMMUNICATION = "oi_communication"
    OI_MEMORY = "oi_memory"
    OI_RECOMMENDATION = "oi_recommendation"
    OI_SOP = "oi_sop"
    OI_TONALITY = "oi_tonality"
    SESSION = "session"
    SUPERVISOR = "supervisor"


__all__ = ["OperationalSubstrate"]
