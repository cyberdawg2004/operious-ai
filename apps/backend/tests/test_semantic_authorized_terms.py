"""Fix: authorized-remediation allowlist for grounding-as-governance.

Root cause (live forensics): the diagnostic model proposed standard remediations
("credit", "rma") absent from the cited SOP, so they were flagged as INTRODUCED
and the execution was terminally rejected (dead-lettered). A tenant's authorized
remediation vocabulary should be permitted even when not literally grounded,
while genuinely off-policy terms (chargeback, fraud, legal) still fail closed.
"""

from __future__ import annotations

import pytest

from app.cognition.exceptions import CognitionSemanticValidationError
from app.cognition.semantic import validate_governance_terms


def test_authorized_terms_allow_introduced_remediations() -> None:
    # Ticket + SOP ground "refund"/"replacement"; model also says "credit"/"rma".
    result = validate_governance_terms(
        canonical_text="my anker power bank will not charge",
        allowed_text="charging SOP: warranty replacement and refund eligibility",
        output_text="recommend a replacement or refund; customer may request an rma or store credit",
        authorized_terms=frozenset({"refund", "replacement", "credit", "rma", "escalate"}),
    )
    assert result.valid
    assert "credit" not in result.introduced_terms
    assert "rma" not in result.introduced_terms


def test_unauthorized_term_still_fails_closed() -> None:
    # "fraud" is neither grounded nor authorized -> must still reject.
    with pytest.raises(CognitionSemanticValidationError):
        validate_governance_terms(
            canonical_text="charging issue",
            allowed_text="charging SOP: replacement and refund",
            output_text="this looks like fraud; deny the refund",
            authorized_terms=frozenset({"refund", "replacement", "credit", "rma", "escalate"}),
        )


def test_missing_term_still_fails_closed_despite_allowlist() -> None:
    # Customer explicitly said "refund"; model dropping it is still a drift.
    with pytest.raises(CognitionSemanticValidationError):
        validate_governance_terms(
            canonical_text="I demand a refund now",
            allowed_text="I demand a refund now",
            output_text="we will send a replacement",
            authorized_terms=frozenset({"refund", "replacement", "credit", "rma"}),
        )


def test_default_no_authorized_terms_is_unchanged() -> None:
    # Backward compatible: without an allowlist, introduced terms still reject.
    with pytest.raises(CognitionSemanticValidationError):
        validate_governance_terms(
            canonical_text="charging issue",
            allowed_text="charging SOP without remediation vocabulary",
            output_text="offer a refund",
        )
