from __future__ import annotations

import pytest

from app.runtime.customer_email_template import (
    derive_ticket_reference,
    is_clean_human_name,
    render_customer_email_body,
    render_customer_email_subject,
    strip_citation_marks,
    tenant_display_name,
)


def test_derive_ticket_reference_is_stable_for_same_session() -> None:
    session_id = "0e3b663b-aa09-5434-ae0b-20e64723abf0"

    assert derive_ticket_reference(session_id) == "OP-0E3B663B"
    assert derive_ticket_reference(session_id) == derive_ticket_reference(session_id)


def test_derive_ticket_reference_handles_non_uuid_session_ids() -> None:
    reference = derive_ticket_reference("session-123")

    assert reference.startswith("OP-")
    assert len(reference) == len("OP-XXXXXXXX")


def test_tenant_display_name_derives_from_slug() -> None:
    assert tenant_display_name("anker-pilot") == "Anker"
    assert tenant_display_name("acme") == "Acme"
    assert tenant_display_name("") == "Support"


def test_render_customer_email_subject_appends_ticket_once() -> None:
    subject = render_customer_email_subject(
        subject="Re: PowerCore support",
        ticket_reference="OP-0E3B663B",
    )

    assert subject == "Re: PowerCore support [Ticket #OP-0E3B663B]"

    repeated = render_customer_email_subject(
        subject=subject,
        ticket_reference="OP-0E3B663B",
    )
    assert repeated == subject


def test_render_customer_email_body_includes_greeting_ticket_and_signoff() -> None:
    body = render_customer_email_body(
        body="Please try resetting the device once.",
        ticket_reference="OP-0E3B663B",
        tenant_id="anker-pilot",
        customer_display_name=None,
    )

    assert body.startswith("Dear Customer,\n")
    assert "Please try resetting the device once." in body
    assert "ticket number: OP-0E3B663B" in body
    assert body.endswith("The Anker Support Team")


def test_render_customer_email_body_uses_customer_display_name() -> None:
    body = render_customer_email_body(
        body="Please try resetting the device once.",
        ticket_reference="OP-0E3B663B",
        tenant_id="anker-pilot",
        customer_display_name="Jordan Smith",
    )

    assert body.startswith("Dear Jordan Smith,\n")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Reset the device [1].", "Reset the device."),
        ("Reset the device[1].", "Reset the device."),
        ("This is documented [12] in the manual.", "This is documented in the manual."),
        ("Two sources agree [1,6] on this.", "Two sources agree on this."),
        ("Three sources agree [1, 2, 3] here.", "Three sources agree here."),
        ("No citations here.", "No citations here."),
        ("Back to back [1][2] citations.", "Back to back citations."),
        ("Trailing citation [4]", "Trailing citation"),
    ],
)
def test_strip_citation_marks_removes_bracket_numbers(
    text: str, expected: str
) -> None:
    assert strip_citation_marks(text) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Imad Baraja", True),
        ("Imad", True),
        ("Mary-Jane O'Connor", True),
        (None, False),
        ("", False),
        ("a", False),
        ("imad.baraja123", False),
        ("imad@example.com", False),
        ("noreply", False),
        ("No Reply", False),
        ("Support Team", False),
        ("12345", False),
        ("Jordan_Smith", False),
        ("x" * 61, False),
    ],
)
def test_is_clean_human_name(value: str | None, expected: bool) -> None:
    assert is_clean_human_name(value) is expected


def test_render_customer_email_body_falls_back_for_garbled_name() -> None:
    body = render_customer_email_body(
        body="Please try resetting the device once.",
        ticket_reference="OP-0E3B663B",
        tenant_id="anker-pilot",
        customer_display_name="imad.baraja123",
    )

    assert body.startswith("Dear Customer,\n")


def test_render_customer_email_body_strips_citations_from_render_only() -> None:
    cited_body = "Reset the device [1]. This resolves most issues [2, 3]."

    rendered = render_customer_email_body(
        body=cited_body,
        ticket_reference="OP-0E3B663B",
        tenant_id="anker-pilot",
        customer_display_name=None,
    )

    assert "[1]" not in rendered
    assert "[2, 3]" not in rendered
    assert "Reset the device. This resolves most issues." in rendered
    # The caller's copy of the governed body is untouched.
    assert cited_body == "Reset the device [1]. This resolves most issues [2, 3]."
