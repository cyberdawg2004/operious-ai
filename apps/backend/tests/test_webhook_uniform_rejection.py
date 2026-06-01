"""Spec 1b — uniform webhook rejection prevents route/tenant enumeration (#24)."""

from __future__ import annotations

from app.services.ticket_ingress_service import (
    WEBHOOK_REJECTED_CODE,
    _uniform_webhook_rejection,
)

_REASONS = (
    "unknown_channel_route",
    "tenant_route_mismatch",
    "invalid_signature",
    "missing_signature",
)


def test_all_rejection_reasons_share_one_response() -> None:
    rejections = [_uniform_webhook_rejection(reason) for reason in _REASONS]
    assert {r.status_code for r in rejections} == {401}
    assert {r.code for r in rejections} == {WEBHOOK_REJECTED_CODE}
    assert {r.reason for r in rejections} == {WEBHOOK_REJECTED_CODE}


def test_rejection_leaks_no_cause_detail() -> None:
    rej = _uniform_webhook_rejection("invalid_signature")
    assert "signature" not in rej.reason
    assert "tenant" not in rej.reason
    assert "route" not in rej.reason
