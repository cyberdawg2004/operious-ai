"""Placeholder convention for tenant message templates (Phase W0).

Templates (TenantKnowledgeDocumentType.TEMPLATE) carry plain-text
content that MAY reference variables to be substituted at send time —
e.g. a probe asking for a missing invoice might read:

    "Hi! To process your request for order {order_id}, we still need:
    {missing_fields}. Could you reply with that?"

Convention
----------
A placeholder is a ``{name}`` token where ``name`` matches
``^[a-z][a-z0-9_]*$`` (snake_case, must start with a letter). This is
deliberately the same shape as a Python ``str.format()`` field name,
since that is the obvious, boring substitution mechanism a future
probe-dispatch step would reach for — but no substitution happens here.
This module only lets a caller discover which placeholders a template
declares, so storage/validation can reason about them (e.g. "does this
template reference {order_id}?") without yet deciding how or when
substitution happens — that is W4's job, not W0's.

Literal braces that are not a valid placeholder name (e.g. malformed
``{Order ID}`` or an escaped ``{{not_a_placeholder}}``) are not
extracted — ``extract_placeholders`` is intentionally conservative
rather than guessing at intent.

Substitution (W4)
-----------------
``substitute_placeholders`` is the mechanical piece this module
deferred: it fills ``{name}`` tokens from a caller-supplied value map,
using the EXACT SAME pattern ``extract_placeholders`` validates against
— so a template that passed validation at save time substitutes
identically here, never surprising a caller with a token it didn't
know to provide. A name absent from the map, or present with a blank
value, is replaced with a visible ``[missing: name]`` marker rather
than silently dropped or fabricated — a human reviewing the resulting
draft must be able to see exactly what the system did not know,
because this is a customer-facing message and nothing here is ever
sent automatically.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([a-z][a-z0-9_]*)\}(?!\})")


def extract_placeholders(content: str) -> frozenset[str]:
    """Return the set of placeholder names referenced in ``content``.

    Pure and read-only — does not validate that the names are ones a
    future caller will actually be able to fill in; that is a
    substitution-time concern (W4), not a storage-time one.
    """
    return frozenset(_PLACEHOLDER_PATTERN.findall(content))


def substitute_placeholders(
    content: str,
    values: Mapping[str, str | None],
) -> str:
    """Fill ``{name}`` tokens in ``content`` from ``values``.

    Never fabricates: a placeholder with no entry in ``values``, or an
    entry that is ``None`` or blank, becomes ``[missing: name]`` in the
    output — visible, not silently omitted, not invented.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = values.get(name)
        if value is None or not value.strip():
            return f"[missing: {name}]"
        return value

    return _PLACEHOLDER_PATTERN.sub(_replace, content)


__all__ = ["extract_placeholders", "substitute_placeholders"]
