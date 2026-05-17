"""Substrate-internal supervision helpers.

DISCIPLINE: this module is NOT the operational supervision
substrate (`app.supervisor` — a sibling). It is a substrate-
internal collection of pure scoring + classification helpers
the runtimes use to score deterministic baselines (e.g. tonality
confidence, candidate-pattern strength, recommendation severity).

NOTHING in this module mutates anything. Pure functions only.
"""

from app.organizational_intelligence.supervision.scoring import (
    candidate_strength,
    finding_severity_weight,
    score_communication_match,
)

__all__ = [
    "candidate_strength",
    "finding_severity_weight",
    "score_communication_match",
]
