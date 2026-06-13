"""Professional email formatting for governed customer replies.

Wraps the governed reply body (the exact text approved by governance and
hashed into ``resolution_outbound_drafts``) with a customer-facing greeting,
closing, and ticket reference. This wrapping happens at send time only and
never touches the governed draft body or its checksum.
"""

from __future__ import annotations

import uuid

_DEFAULT_CUSTOMER_NAME = "Customer"
_TICKET_PREFIX = "OP"


def derive_ticket_reference(session_id: str) -> str:
    """Derive a stable, customer-facing ticket reference from a session id.

    The same session always yields the same reference, so repeat replies
    and merged follow-ups on one ticket share a single reference number.
    """

    try:
        digits = uuid.UUID(session_id).hex[:8].upper()
    except ValueError:
        digits = "".join(ch for ch in session_id.upper() if ch.isalnum())[:8]
        digits = digits.ljust(8, "0")
    return f"{_TICKET_PREFIX}-{digits}"


def tenant_display_name(tenant_id: str) -> str:
    """Best-effort human-readable tenant name from a tenant_id slug."""

    head = tenant_id.split("-", 1)[0].strip()
    if not head:
        return "Support"
    return head[:1].upper() + head[1:]


def render_customer_email_subject(
    *,
    subject: str,
    ticket_reference: str,
) -> str:
    """Append the ticket reference to an outbound email subject."""

    if ticket_reference in subject:
        return subject
    return f"{subject} [Ticket #{ticket_reference}]"


def render_customer_email_body(
    *,
    body: str,
    ticket_reference: str,
    tenant_id: str,
    customer_display_name: str | None = None,
) -> str:
    """Wrap a governed reply body in a professional email structure."""

    customer_name = (customer_display_name or "").strip() or _DEFAULT_CUSTOMER_NAME
    tenant_name = tenant_display_name(tenant_id)
    return (
        f"Dear {customer_name},\n"
        "\n"
        f"{body.strip()}\n"
        "\n"
        "If you have any further questions or need to follow up on this "
        "request, please reply to this email and reference your ticket "
        f"number: {ticket_reference}.\n"
        "\n"
        "Best regards,\n"
        f"The {tenant_name} Support Team"
    )


__all__ = [
    "derive_ticket_reference",
    "render_customer_email_body",
    "render_customer_email_subject",
    "tenant_display_name",
]
