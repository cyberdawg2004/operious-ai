"""WhatsApp-native formatting for governed customer replies.

WhatsApp is a chat thread, not a letter: unlike
``render_customer_email_body``, this intentionally adds no "Dear X,"
greeting and no "Best regards" sign-off -- the generated reply's own
acknowledgment segment already carries the courtesy opener, and a
formal email-style envelope would look out of place in a WhatsApp
thread. What it DOES share with the email renderer is the citation-mark
strip: the customer must never see a literal "[1]" on either channel,
so this reuses ``strip_citation_marks`` rather than duplicating it.
"""

from __future__ import annotations

import re

from app.runtime.customer_email_template import strip_citation_marks

# WhatsApp's own markup uses a single asterisk for bold ("*bold*"), not
# Markdown's double asterisk. Nothing in this codebase emits Markdown
# bold today, but if a future segment or template ever does, it must
# render as WhatsApp's native markup rather than literal double
# asterisks reaching the customer.
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*")


def render_customer_whatsapp_body(*, body: str) -> str:
    """Render a governed reply body for WhatsApp.

    Strips citation marks (parity with email -- see
    ``render_customer_email_body``) and converts any Markdown-style
    ``**bold**`` to WhatsApp's single-asterisk ``*bold*``. Adds no
    further structure: the body's own paragraph breaks (from
    ``render_grounded_reply``) are left exactly as generated.
    """

    rendered = strip_citation_marks(body.strip())
    return _MARKDOWN_BOLD_PATTERN.sub(r"*\1*", rendered)


__all__ = ["render_customer_whatsapp_body"]
