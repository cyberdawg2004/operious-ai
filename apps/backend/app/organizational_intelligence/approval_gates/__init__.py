"""Substrate-internal approval-gate helpers.

Renamed from ``app.organizational_intelligence.governance`` to
``app.organizational_intelligence.approval_gates`` in PR-A3 so the
import path is visually unambiguous against the constitutional
``app.governance`` substrate. The two namespaces previously shared
a leaf name (``governance``) and required disambiguation by
comment at every import site — the rename closes that debt at
the namespace level rather than at the prose level.

Sibling-substrate isolation rule: this module does NOT import
from ``app.governance`` — that would couple the intelligence
substrate to operational governance and blur semantic ownership.
The intelligence substrate enforces its OWN approval discipline
internally; ``app.governance`` enforces operational governance.
The two are constitutional siblings, never delegates.

The discipline this module enforces is unchanged: status
transitions out of CANDIDATE / PROPOSED require an
``ApprovalRecord`` with the matching ``target_id`` and
``decision``.
"""

from app.organizational_intelligence.approval_gates.approval_gate import (
    require_approval_for_promotion,
    require_approval_for_registration,
    require_approval_for_review,
    require_approval_for_supersession,
)

__all__ = [
    "require_approval_for_promotion",
    "require_approval_for_registration",
    "require_approval_for_review",
    "require_approval_for_supersession",
]
