"""Professional email formatting for governed customer replies.

Wraps the governed reply body (the exact text approved by governance and
hashed into ``resolution_outbound_drafts``) with a customer-facing greeting,
closing, and ticket reference. This wrapping happens at send time only and
never touches the governed draft body or its checksum.

This module also strips visible citation marks (e.g. ``[1]``, ``[1,6]``)
from the rendered body. Citations remain in the governed draft and are
still evaluated by grounding governance against the cited text -- only the
customer-facing rendering at this seam removes the bracket markers.
"""

from __future__ import annotations

import re
import uuid

_DEFAULT_CUSTOMER_NAME = "Customer"
_TICKET_PREFIX = "OP"

# Matches bracketed citation marks such as "[1]", "[12]", "[1,6]",
# "[1, 2, 3]", including any leading whitespace so removal doesn't leave
# a dangling space before following punctuation.
_CITATION_PATTERN = re.compile(r"\s*\[\s*\d+(?:\s*,\s*\d+)*\s*\]")
_MULTI_SPACE_PATTERN = re.compile(r" {2,}")
_SPACE_BEFORE_PUNCTUATION_PATTERN = re.compile(r" +([.,!?;:])")

# Conservative human-name shape: letters, spaces, hyphens, apostrophes only.
_HUMAN_NAME_PATTERN = re.compile(r"^[A-Za-z]+(?:[ '\-][A-Za-z]+)*$")
_NON_HUMAN_NAME_TOKENS = frozenset(
    {
        "noreply",
        "no-reply",
        "donotreply",
        "do-not-reply",
        "support",
        "admin",
        "administrator",
        "info",
        "notification",
        "notifications",
        "mailer",
        "postmaster",
        "webmaster",
        "system",
        "autoreply",
        "auto-reply",
        "customer",
        "service",
        "team",
        "billing",
        "sales",
        "alert",
        "alerts",
        "robot",
        "bot",
    }
)
_MIN_NAME_LENGTH = 2
_MAX_NAME_LENGTH = 60


def strip_citation_marks(text: str) -> str:
    """Remove visible "[1]"/"[1,6]"-style citation marks from ``text``.

    Collapses any whitespace left behind so the prose reads cleanly
    (no doubled spaces, no space before trailing punctuation).
    """

    stripped = _CITATION_PATTERN.sub("", text)
    stripped = _MULTI_SPACE_PATTERN.sub(" ", stripped)
    stripped = _SPACE_BEFORE_PUNCTUATION_PATTERN.sub(r"\1", stripped)
    return stripped


def is_clean_human_name(value: str | None) -> bool:
    """Return ``True`` only for a conservative, clean human display name.

    Rejects email addresses, local-part-shaped strings (digits,
    underscores, dots), generic mailbox names ("noreply", "support",
    ...), and anything outside a plausible human-name shape.
    """

    if value is None:
        return False
    candidate = value.strip()
    if not (_MIN_NAME_LENGTH <= len(candidate) <= _MAX_NAME_LENGTH):
        return False
    if not _HUMAN_NAME_PATTERN.match(candidate):
        return False
    tokens = candidate.lower().split()
    if any(token.strip("-'") in _NON_HUMAN_NAME_TOKENS for token in tokens):
        return False
    if "".join(tokens) in _NON_HUMAN_NAME_TOKENS:
        return False
    return True


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
    """Wrap a governed reply body in a professional email structure.

    The governed ``body`` (and its checksum, computed upstream from this
    exact text) is left untouched; only the rendered copy has citation
    marks stripped for the customer-facing email.
    """

    candidate_name = (customer_display_name or "").strip()
    customer_name = (
        candidate_name if is_clean_human_name(candidate_name) else _DEFAULT_CUSTOMER_NAME
    )
    tenant_name = tenant_display_name(tenant_id)
    rendered_body = strip_citation_marks(body.strip())
    return (
        f"Dear {customer_name},\n"
        "\n"
        f"{rendered_body}\n"
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
    "is_clean_human_name",
    "render_customer_email_body",
    "render_customer_email_subject",
    "strip_citation_marks",
    "tenant_display_name",
]
