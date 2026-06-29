from __future__ import annotations

from app.runtime.customer_whatsapp_template import render_customer_whatsapp_body


def test_strips_citation_marks_same_as_email() -> None:
    rendered = render_customer_whatsapp_body(
        body="We checked your order and confirmed it's within warranty [1]."
    )

    assert "[1]" not in rendered
    assert rendered == "We checked your order and confirmed it's within warranty."


def test_strips_multiple_citation_marks() -> None:
    rendered = render_customer_whatsapp_body(
        body="This is covered by our policy [1,2] and the return window [3]."
    )

    assert "[1,2]" not in rendered
    assert "[3]" not in rendered


def test_adds_no_email_style_greeting_or_signoff() -> None:
    rendered = render_customer_whatsapp_body(body="Please try resetting the device once.")

    assert rendered == "Please try resetting the device once."
    assert "Dear" not in rendered
    assert "Best regards" not in rendered


def test_converts_markdown_bold_to_whatsapp_single_asterisk() -> None:
    rendered = render_customer_whatsapp_body(
        body="Your order is **confirmed** for replacement."
    )

    assert rendered == "Your order is *confirmed* for replacement."
    assert "**" not in rendered


def test_preserves_paragraph_breaks_from_segment_rendering() -> None:
    rendered = render_customer_whatsapp_body(
        body="Thanks for reaching out.\n\n1. What is your order number?\n2. What is the seller name?"
    )

    assert rendered == (
        "Thanks for reaching out.\n\n1. What is your order number?\n2. What is the seller name?"
    )
