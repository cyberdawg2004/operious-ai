"""Deterministic-seed projection helpers.

This module owns the substrate's doctrine for projecting optional
identifiers into deterministic UUID5 seed strings without collapsing
distinct authority states.

Constitutional problem this module closes (audit CO-1, CO-2, CO-3)
----------------------------------------------------------------
Before Wedge B4 every deriver in the substrate projected an optional
identifier through ``value or ''``:

    seed = f"...{tenant_id or ''}|..."

That projection mapped TWO constitutionally distinct authority states
to the SAME seed string:

* ``tenant_id is None``  → projected as ``""``
* ``tenant_id == ""``    → projected as ``""``

Because UUID5 is a deterministic function of (namespace, seed), both
authorities hashed to byte-identical identifiers. Replay
reconstruction could no longer distinguish "tenantless operation"
from "operation with empty-string tenant" — two distinct authority
chains collapsed into one.

The fix (this module)
---------------------
``project_optional_str(value)`` projects ``None`` to a NUL-bounded
sentinel that:

1. Is structurally impossible to produce from any well-formed
   identifier — NUL bytes never appear in tenant ids, principal ids,
   correlation ids, request ids, or any other identifier the
   substrate accepts at its boundaries.
2. Is distinct from the empty string (``""``), so the two authority
   states project to different seeds and therefore to different
   UUID5 outputs.
3. Is bracketed so a pathological input that contained a single
   embedded NUL byte still cannot collide with the sentinel.

The helper is a leaf primitive — pure function, no I/O, no global
state, no sibling-substrate imports. ``app/identity/`` remains a
leaf substrate.

What this module does NOT do
----------------------------
* It does not validate that the supplied value is a legitimate
  identifier — call sites that want validation use the ``coerce_*``
  helpers in :mod:`app.identity.primitives`.
* It does not change the UUID derivation architecture — derivers
  still call :func:`uuid.uuid5` with the same per-substrate
  namespace constants.
* It does not migrate previously-derived UUIDs. Per the wedge B4
  doctrine, ``None``-tenant UUIDs produced before the projection
  change are constitutionally distinct from the new ones and must
  not be reconstructed via the new helper.
"""

from __future__ import annotations

from typing import Final

# NUL-bounded sentinel. NUL (``\x00``) is forbidden in JSON strings,
# in URL components, in shell arguments, in SQL identifiers, in
# database column values when ``NOT NULL`` is enforced, and in every
# protocol the substrate's boundaries accept input from. The brackets
# disambiguate from any pathological NUL-containing string.
_NONE_SENTINEL: Final[str] = "\x00<none>\x00"


def project_optional_str(value: str | None) -> str:
    """Project ``value`` into an unambiguous deterministic-seed component.

    The doctrine:

    * ``None``      → constitutional NUL-bounded sentinel
    * ``""``        → empty string (verbatim)
    * any other str → returned verbatim

    Replay-safe: same input produces byte-identical output every call.
    Authority-distinct: ``project_optional_str(None) !=
    project_optional_str("")`` always.
    """
    if value is None:
        return _NONE_SENTINEL
    return value


__all__ = ["project_optional_str"]
