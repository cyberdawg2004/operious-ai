from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.persistence import CaseApprovalRecord
from app.core.config import get_settings
from app.workers.case_approval_outbox_tasks import (
    _ENTRY_CATEGORY_LABELS,
    _email_body,
    _friendly_entry_category_label,
)

_NOW = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


def _case(
    *,
    entry_category: CaseApprovalEntryCategory = (
        CaseApprovalEntryCategory.RESOLUTION_REQUIRE_APPROVAL
    ),
) -> CaseApprovalRecord:
    return CaseApprovalRecord(
        approval_case_id=str(uuid.uuid4()),
        tenant_id="tenant-email-body-test",
        session_id=None,
        execution_id=None,
        dispatch_id=None,
        entry_category=entry_category,
        status=CaseApprovalStatus.AWAITING_APPROVAL,
        requested_at=_NOW,
        dedup_key="dedup-1",
        ticket_ref="OP-12345678",
        product="some-product",
        issue_summary="Won't charge, missing order number.",
    )


def test_break_control_i_friendly_label_not_raw_enum() -> None:
    body = _email_body(_case())

    assert "Category: Resolution — approval required" in body
    assert "resolution_require_approval" not in body


def test_friendly_label_covers_every_entry_category() -> None:
    """Every CaseApprovalEntryCategory value has a label -- mirrors
    categoryTitle() in case-approvals-inbox.tsx exactly."""
    for category in CaseApprovalEntryCategory:
        label = _friendly_entry_category_label(category.value)
        assert label != category.value
        assert label == _ENTRY_CATEGORY_LABELS[category.value]


def test_unknown_category_falls_back_to_raw_value() -> None:
    assert _friendly_entry_category_label("some_future_category") == "some_future_category"


def test_break_control_ii_names_the_reply_reviews_surface() -> None:
    body = _email_body(_case())

    assert "Needs Attention → Message Approvals" in body


def test_break_control_iii_includes_deep_link_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("COMMAND_CENTER_BASE_URL", "https://cc.example.com/")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        body = _email_body(_case())
        assert "https://cc.example.com/dashboard/case-approvals" in body
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_no_deep_link_line_when_command_center_url_unset(monkeypatch) -> None:
    monkeypatch.delenv("COMMAND_CENTER_BASE_URL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        body = _email_body(_case())
        assert "dashboard/case-approvals" not in body
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_break_control_iv_label_map_is_generic_no_tenant_hardcoding() -> None:
    for label in _ENTRY_CATEGORY_LABELS.values():
        assert "anker" not in label.lower()
        assert "powercore" not in label.lower()
