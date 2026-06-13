from __future__ import annotations

from app.runtime.customer_email_template import (
    derive_ticket_reference,
    render_customer_email_body,
    render_customer_email_subject,
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
