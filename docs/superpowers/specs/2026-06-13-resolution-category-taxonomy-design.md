# Tenant-Configurable Resolution Category Taxonomy (Follow-up Stub)

- **Date:** 2026-06-13
- **Status:** Stub — tracker for follow-up, not yet ready for implementation
- **Sub-project:** Customer support autonomy — governance gate hardening
- **Owner:** backend
- **Depends on:** `2026-06-12-tenant-configurable-resolution-autonomy-design.md` (§6)

## Purpose

This is a tracker, not a design. It records the residual tenant-agnosticism gaps
identified in §6 of the resolution-autonomy spec so they aren't lost, and scopes what a
follow-up design would need to cover. None of the items below are regressions — they are
pre-existing hardcoding that the resolution-autonomy spec deliberately left untouched.

## Residual gaps (from resolution-autonomy spec §6)

1. **`_resolution_category()`** (`app/runtime/resolution_runtime.py`) reclassifies
   `diagnostic_category` via hardcoded English keyword matches (`"warranty"`,
   `"replacement"`, `"refund"`, `"charge"`/`"battery"`/`"power"`, etc.) to produce the
   category string that `category_allowlist` (from the new `resolution_autonomy` policy)
   matches against. A tenant's allowlist only works correctly if their issues happen to
   map onto these keyword buckets.

2. **`_recommended_actions()`** (`app/runtime/resolution_runtime.py`) hardcodes which tool
   (`warranty.claim`, `refund.request`, `warehouse.repair.report`) and payload shape
   applies per category, keyed off the same hardcoded category strings as (1).

3. **Remedy-keyword vocabulary** inside `_monetary_commitment_exceeds_threshold`
   (`"refund"`, `"replace"`, `"warranty"`) and `_UNSUPPORTED_PROMISE_PATTERNS` remain
   English/e-commerce-shaped. For tenants outside that domain (healthcare, banking, etc.)
   the monetary-commitment guard never fires — safe (fails toward an extra approval step
   not triggering), but inert.

## Candidate follow-up shape (not designed yet)

- A tenant-defined category taxonomy, declared at onboarding and used directly by the
  diagnostic classifier, so `_resolution_category` becomes a thin pass-through of
  `diagnostic_category` rather than a reclassifier.
- A tenant-configured action-mapping (category → tool + payload shape) to replace the
  hardcoded table in `_recommended_actions()`.
- A tenant-configured remedy-commitment keyword list, analogous to `category_allowlist`,
  feeding `_monetary_commitment_exceeds_threshold` and `_UNSUPPORTED_PROMISE_PATTERNS`.

## Next steps

When this is picked up, write a full design spec following
`docs/superpowers/specs/2026-06-12-tenant-configurable-resolution-autonomy-design.md` as a
template: survey existing config surfaces, define the policy schema, fail-closed behavior,
and a test/break-control plan covering each of the three items above.
