"""Substrate-internal approval-gate helpers.

DISCIPLINE: this module is NOT the operational governance
substrate (`app.governance` — a sibling). It is a substrate-
internal collection of pure functions that enforce the SINGLE
most important rule of Sprint O:

    Status transitions out of CANDIDATE / PROPOSED require an
    `ApprovalRecord` with the matching ``target_id`` and
    ``decision``.

Sibling-substrate isolation rule: this module does NOT import
from `app.governance` — that would couple the intelligence
substrate to operational governance and blur semantic ownership.
The intelligence substrate enforces its OWN approval discipline
internally.
"""

from app.organizational_intelligence.governance.approval_gate import (
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
