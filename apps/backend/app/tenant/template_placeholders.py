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

_MISSING_MARKER_PREFIX = "[missing: "

# The two names _probe_substitution_values always derives itself
# (app.runtime.resolution_runtime), regardless of which order fields were
# extracted -- combined with the extracted order field names themselves
# in fillable_template_placeholders() below.
_ALWAYS_DERIVED_PLACEHOLDERS = frozenset({"claim_type", "missing_fields"})

_fillable_cache: frozenset[str] | None = None


class TemplatePlaceholderError(ValueError):
    """Raised when a template references a placeholder that can never be
    filled at send time."""


def fillable_template_placeholders() -> frozenset[str]:
    """The complete set of names a template's ``{placeholder}`` can ever
    resolve to: the extracted order fields (app.cognition.extraction)
    plus the two names always derived regardless of extraction. Anything
    outside this set can never be filled at send time — see
    ``validate_template_placeholders``, the authoring-time guard that
    rejects such a template before it can ever be approved.

    Imported lazily, not at module level: app.cognition.extraction's
    parent package eagerly imports app.runtime.resolution_runtime, which
    imports THIS module — a module-level import here would be a circular
    import.
    """
    global _fillable_cache
    if _fillable_cache is None:
        from app.cognition.extraction import EXTRACTED_ORDER_FIELD_NAMES

        _fillable_cache = (
            frozenset(EXTRACTED_ORDER_FIELD_NAMES) | _ALWAYS_DERIVED_PLACEHOLDERS
        )
    return _fillable_cache


def extract_placeholders(content: str) -> frozenset[str]:
    """Return the set of placeholder names referenced in ``content``.

    Pure and read-only — does not validate that the names are ones a
    future caller will actually be able to fill in; that is
    ``validate_template_placeholders``'s job, not this function's.
    """
    return frozenset(_PLACEHOLDER_PATTERN.findall(content))


def validate_template_placeholders(content: str) -> None:
    """Authoring-time guard: reject a template that references a
    placeholder outside ``fillable_template_placeholders()``.

    Without this, an unknown placeholder name was never caught anywhere
    (extract_placeholders had zero callers) and would silently render as
    a literal ``[missing: name]`` string in a customer-facing reply —
    this is what closes that gap at the point a template can still be
    rejected instead of approved.
    """
    fillable = fillable_template_placeholders()
    unknown = extract_placeholders(content) - fillable
    if unknown:
        raise TemplatePlaceholderError(
            "template references placeholder(s) that can never be filled: "
            f"{', '.join(sorted(unknown))} -- fillable placeholders are: "
            f"{', '.join(sorted(fillable))}"
        )


def contains_unresolved_placeholder_marker(text: str) -> bool:
    """Send-time backstop: True if ``text`` still contains a literal
    ``[missing: name]`` marker left by ``substitute_placeholders``.

    Defense in depth alongside ``validate_template_placeholders``: even a
    template that only declares fillable placeholders can still render a
    marker if the specific case at hand didn't actually have a value for
    one of them (e.g. a template asking about ``{seller}`` when this
    ticket's extraction never found a seller). A rendered reply
    containing this marker must never reach a customer via auto-send.
    """
    return _MISSING_MARKER_PREFIX in text


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
            return f"{_MISSING_MARKER_PREFIX}{name}]"
        return value

    return _PLACEHOLDER_PATTERN.sub(_replace, content)


__all__ = [
    "TemplatePlaceholderError",
    "contains_unresolved_placeholder_marker",
    "extract_placeholders",
    "fillable_template_placeholders",
    "substitute_placeholders",
    "validate_template_placeholders",
]
