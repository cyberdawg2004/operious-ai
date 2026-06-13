# Tenant-Defined Category Taxonomy, Action Mapping, and Remedy Vocabulary

- **Date:** 2026-06-13
- **Status:** Draft — awaiting approval (spec only, no implementation)
- **Sub-project:** Customer support autonomy — governance gate hardening
- **Owner:** backend
- **Supersedes:** `2026-06-13-resolution-category-taxonomy-design.md` (stub tracker)
- **Depends on:** `2026-06-12-tenant-configurable-resolution-autonomy-design.md`
  (already implemented: `resolution_autonomy` policy, `category_allowlist`,
  `monetary_commitment_threshold_cents`)

## 1. Context and problem

The 2026-06-12 spec made the *autonomy gate* tenant-configurable (which category
strings are allowed to auto-send, and at what monetary threshold). It explicitly
left three layers untouched, flagged as residual gaps (§6 of that spec). This spec
designs the fix for all three — plus a fourth layer discovered while tracing the
data flow, which is actually the **root** of the problem:

1. **`DiagnosticCategory` enum + diagnostic system prompt**
   (`app/cognition/models.py:68-75`, `app/cognition/diagnostic_runtime.py:97-98,
   1256`) — the diagnostic LLM's structured-output schema is a *closed, hardcoded
   Pydantic enum* (`ACCOUNT_ISSUE`, `CHARGING_ISSUE`, `CONNECTIVITY_ISSUE`,
   `PRODUCT_DEFECT`, `REFUND_ISSUE`, `UNKNOWN_ISSUE`), and the system prompt
   (`_render_system_prompt`, line 1256) lists exactly these six values as the only
   legal `category` outputs. `_parse_output` (lines 971-998) raises if the LLM
   returns anything else. **This is upstream of everything else** — even before
   `_resolution_category()` runs, the diagnostic stage cannot produce a category
   outside this electronics/e-commerce-shaped set of six.

2. **`_resolution_category()`** (`app/runtime/resolution_runtime.py:682-699`) —
   re-classifies via hardcoded English keyword matches (`"warranty"`,
   `"refund"`, `"charging"`/`"battery"`/`"power"`, etc.), independent of (1)'s
   output for most cases.

3. **`_recommended_actions()`** (`resolution_runtime.py:702-829`) — hardcodes
   category → `{tool_name, payload, target_resource_id}` for `warranty.claim`,
   `refund.request`, `warehouse.repair.report`.

4. **Remedy vocabulary** — `_monetary_commitment_exceeds_threshold` (lines
   941-951) only checks the money-threshold guard if the reply text contains
   `"refund"`/`"replacement"`/`"replace"`/`"warranty"`; `_UNSUPPORTED_PROMISE_PATTERNS`
   (lines 109-122) is a closed set of English refund/replacement/warranty phrases
   used for a hard DENY.

A bank tenant's diagnostic LLM **cannot** classify a "someone used my card without
authorization" ticket as `"disputed_transaction"` — the schema doesn't allow it,
the prompt doesn't mention it, and even if it somehow emitted that string,
`_parse_output` would raise. Everything downstream is moot until (1) is fixed.

## 2. Design overview

One new policy type, `resolution_taxonomy`, stored the same way as
`resolution_autonomy` (`tenant_governance_policies`, generic
`(tenant_id, policy_type, parameters jsonb, status, version)`, same
propose→approve→apply workflow). It declares:

- The tenant's category taxonomy (id, label, description — used both to *prompt*
  the diagnostic LLM and to *validate* its output).
- Per-category recommended actions (replaces `_recommended_actions()`'s table).
- Tenant-specific monetary-commitment vocabulary (replaces the hardcoded remedy
  keyword list and `_UNSUPPORTED_PROMISE_PATTERNS`).

**Fail-closed default (no `resolution_taxonomy` policy configured):** the
diagnostic stage falls back to a single sentinel category, `"unclassified"`. Every
proposal gets `recommended_actions = (collect_context,)` (no `requires_execution:
true` actions ever generated), and — because `"unclassified"` can never appear in
any tenant's `resolution_autonomy.reply_auto_send.category_allowlist` (it is
reserved, see §3.4) — every proposal requires human approval via the existing
`resolution_autonomy` empty/non-matching-category path. **Nothing new needs to be
added to the gate logic for this** — the existing `category not in
autonomy_policy.reply_auto_send_categories` check (resolution_runtime.py:878)
already produces `PENDING_HUMAN_APPROVAL` for any category, including
`"unclassified"`, that isn't in a configured allowlist.

This composes with the existing `resolution_autonomy` policy unchanged:
`resolution_taxonomy` defines *what categories exist and what they mean*;
`resolution_autonomy` (already shipped) defines *which of those categories may
auto-send and at what monetary ceiling*. Both are required, independently
configured, for a tenant to get auto-send.

## 3. New policy type: `resolution_taxonomy`

### 3.1 Parameters JSON shape

```json
{
  "_schema_version": "1",
  "policy_type": "resolution_taxonomy",
  "parameters": {
    "categories": [
      {
        "id": "disputed_transaction",
        "label": "Disputed transaction",
        "description": "Customer disputes a charge, transfer, or transaction on their account.",
        "recommended_actions": [
          {
            "type": "customer_reply_draft",
            "label": "Share cited dispute-process explanation",
            "requires_execution": false
          },
          {
            "type": "dispute_reversal",
            "label": "Open a transaction dispute case",
            "requires_execution": true,
            "tool_name": "dispute.reversal.request",
            "payload_template": {
              "account_id": null,
              "transaction_id": null,
              "dispute_reason": "Customer-reported unauthorized or incorrect transaction."
            },
            "target_resource_id": "dispute:disputed_transaction"
          },
          {
            "type": "collect_context",
            "label": "Collect transaction date, amount, and merchant details",
            "requires_execution": false
          }
        ]
      },
      {
        "id": "card_lost",
        "label": "Card reported lost or stolen",
        "description": "Customer reports a lost, stolen, or compromised card.",
        "recommended_actions": [
          {
            "type": "customer_reply_draft",
            "label": "Confirm card-blocking steps taken",
            "requires_execution": false
          },
          {
            "type": "block_and_reissue",
            "label": "Block card and issue replacement",
            "requires_execution": true,
            "tool_name": "card.block_and_reissue",
            "payload_template": { "account_id": null, "card_id": null },
            "target_resource_id": "card:card_lost"
          }
        ]
      }
    ],
    "monetary_commitment": {
      "remedy_keywords": ["reverse the charge", "refund the fee", "waive the fee", "credit your account"],
      "currency_symbols": ["$"],
      "currency_codes": ["usd", "dollars"]
    },
    "unsupported_commitment_patterns": [
      "we will reverse the charge",
      "we'll waive the fee",
      "guaranteed reversal"
    ]
  }
}
```

### 3.2 Validation (`validate_resolution_taxonomy_policy_parameters`)

New module `app/runtime/resolution_taxonomy_policy.py`, mirroring
`resolution_autonomy_policy.py`'s structure exactly (same parse/validate/resolve
trio, same `TenantConfigurationRepository.resolve_active_governance_policy`
lookup, same fail-closed-on-missing/invalid posture).

- `categories`: **non-empty** list. Each entry:
  - `id`: non-empty string, unique within the list, **must not equal the
    reserved sentinel `"unclassified"`** (§3.4) — reject the whole policy if it
    does (`ResolutionTaxonomyPolicyParseError`).
  - `label`: non-empty string (human-readable, shown in Approval Inbox / Command
    Center UI — never the raw `id`).
  - `description`: non-empty string. This is injected verbatim into the
    diagnostic system prompt (§4), so it must be a clear, LLM-readable
    description of when this category applies. No length cap beyond the
    existing prompt-size budget (flag for implementation: confirm a
    per-category description length cap, e.g. 500 chars, to bound prompt growth
    with large taxonomies).
  - `recommended_actions`: non-empty list of action dicts, each validated
    structurally:
    - `type`: non-empty string.
    - `label`: non-empty string.
    - `requires_execution`: bool, **required**.
    - If `requires_execution is True`:
      - `tool_name`: non-empty string, **and must be a member of the known
        action-tool registry** (`app/agents/tools/actions/__init__.py` /
        `_DISPATCH_TOOL_NAMES` in `action_governance.py`) — validated at
        propose-time. An unknown `tool_name` is a `ResolutionTaxonomyPolicyParseError`,
        not a silent no-op. This is the only place this spec touches the
        action-tool registry: as a **read-only validation reference**, not a
        modification. (See §6 — this spec does not add, remove, or change any
        action tool or `TenantActionPolicy` behavior.)
      - `payload_template`: a JSON object (no further schema validation here —
        the tool's own invocation path is responsible for payload correctness,
        unchanged from today's hardcoded `_recommended_actions()` payloads,
        which are themselves placeholder-shaped, e.g. `"order_id":
        "unknown_order"`).
      - `target_resource_id`: non-empty string.
    - If `requires_execution is False`: `tool_name`/`payload_template`/
      `target_resource_id` must be absent (reject if present — keeps the two
      action shapes unambiguous).
- `monetary_commitment` (optional object, defaults applied if absent — see
  §3.5):
  - `remedy_keywords`: list of non-empty strings (case-insensitive substring
    match against the lowercased reply text), **may be empty**.
  - `currency_symbols`: list of non-empty strings, **may be empty**.
  - `currency_codes`: list of non-empty strings, **may be empty**.
- `unsupported_commitment_patterns`: list of non-empty strings, **may be
  empty** (default `[]`).

### 3.3 Resolution function

```python
RESOLUTION_TAXONOMY_POLICY_TYPE = "resolution_taxonomy"

@dataclass(frozen=True, slots=True)
class ResolutionTaxonomyCategory:
    id: str
    label: str
    description: str
    recommended_actions: tuple[Mapping[str, Any], ...]

@dataclass(frozen=True, slots=True)
class ResolutionTaxonomyPolicy:
    categories: tuple[ResolutionTaxonomyCategory, ...]
    monetary_remedy_keywords: frozenset[str]
    monetary_currency_symbols: frozenset[str]
    monetary_currency_codes: frozenset[str]
    unsupported_commitment_patterns: frozenset[str]

    def category_ids(self) -> frozenset[str]:
        return frozenset(c.id for c in self.categories)

    def actions_for(self, category_id: str) -> tuple[Mapping[str, Any], ...]:
        for c in self.categories:
            if c.id == category_id:
                return c.recommended_actions
        return (_COLLECT_CONTEXT_FALLBACK_ACTION,)


async def resolve_resolution_taxonomy_policy(
    *, repository: TenantConfigurationRepository | None, tenant_id: str,
) -> ResolutionTaxonomyPolicy:
    """Fail-closed: `repository is None`, no active record, or parse failure
    all return `_empty_taxonomy()` — zero categories, empty vocab sets."""
```

### 3.4 The `"unclassified"` sentinel

`"unclassified"` is a reserved category id, **never** declared by tenant config
(rejected at validation time if a tenant tries). It is the diagnostic stage's
output when:

- No `resolution_taxonomy` policy is configured for the tenant (`_empty_taxonomy()`).
- The diagnostic LLM returns a category string not present in
  `taxonomy.category_ids()` (defense-in-depth — see §4).

`_recommended_actions("unclassified")` (via `actions_for`, §3.3) always returns
`(_COLLECT_CONTEXT_FALLBACK_ACTION,)` — a single `customer_reply_draft`-adjacent,
`requires_execution: false` action, structurally identical to today's
`_recommended_actions()` final fallback branch (lines 823-829). No tenant
configuration, however permissive, can make `"unclassified"` auto-send or execute
an action — `resolution_autonomy.reply_auto_send.category_allowlist` is validated
(§3.2 cross-check, below) to reject `"unclassified"` as a member, so the
`category not in autonomy_policy.reply_auto_send_categories` check
(resolution_runtime.py:878) always holds for it.

**Cross-policy validation** (in
`tenant_config_change_request_service.py`'s policy-payload validation, alongside
the existing `_validate_resolution_autonomy_policy_payload`): when proposing a
`resolution_autonomy` change, if a `resolution_taxonomy` policy is *also* active
for the tenant, validate `category_allowlist ⊆ taxonomy.category_ids()` and
`"unclassified" not in category_allowlist`. If no `resolution_taxonomy` policy is
active yet, skip this cross-check (the `resolution_autonomy` policy would be inert
anyway, per §2 — every category resolves to `"unclassified"` until a taxonomy is
configured). This ordering means: **a tenant must configure `resolution_taxonomy`
before `resolution_autonomy` has any effect** — configuring them in the other
order is allowed (no error) but the autonomy policy stays inert until the taxonomy
exists.

### 3.5 Fail-closed defaults

| Condition | Result |
|---|---|
| `repository is None` | `ResolutionTaxonomyPolicy((), frozenset(), frozenset(), frozenset(), frozenset())` |
| no active `resolution_taxonomy` record | same — empty policy |
| record exists but fails to parse | same — empty policy, logged `resolution_taxonomy_policy_invalid` |
| `monetary_commitment` absent from an otherwise-valid record | `monetary_remedy_keywords = frozenset()`, `currency_symbols = frozenset({"$"})`, `currency_codes = frozenset({"usd", "dollars"})` — i.e. **the existing USD-only money-pattern is the default**, only `remedy_keywords` defaults empty |
| `unsupported_commitment_patterns` absent | `frozenset()` |

An empty `categories` tuple (the "no policy" / "repository is None" / "invalid"
cases) means: diagnostic stage emits `"unclassified"` for everything (§4),
`_recommended_actions` returns the collect-context fallback for everything, and —
combined with the already-shipped `resolution_autonomy` fail-closed behavior —
every proposal requires human approval. **This is identical, in net effect, to
"Operious has never seen this tenant's domain before"** — which is true, and is
the correct default.

## 4. Diagnostic stage: from closed enum to tenant-prompted classification

### 4.1 Schema change — `app/cognition/models.py`

```python
class DiagnosticLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    category: str = Field(min_length=1, max_length=200)  # was: DiagnosticCategory
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=4000, default="")
```

`DiagnosticCategory` (the six-value enum) is **deleted**, not deprecated — it has
exactly one production reference (`DiagnosticLLMOutput.category`), confirmed by
grep. Any test fixtures referencing `DiagnosticCategory.CHARGING_ISSUE` etc. are
updated to plain strings (`"charging_issue"`) — see §8.

### 4.2 Prompt change — `app/cognition/diagnostic_runtime.py`

`_render_system_prompt` (line 1281) and `_full_prompt_snapshot`/output-schema
description (around line 1256, currently `"category": list(_CATEGORY_VALUES)`)
become **tenant-parameterized**:

```python
def _render_system_prompt(
    source_language: str,
    *,
    taxonomy: ResolutionTaxonomyPolicy,
) -> str:
    category_block = _render_taxonomy_categories(taxonomy)
    return _SYSTEM_PROMPT.replace(
        "{source_language}", _normalise_source_language(source_language),
    ).replace(
        "{category_taxonomy}", category_block,
    )


def _render_taxonomy_categories(taxonomy: ResolutionTaxonomyPolicy) -> str:
    if not taxonomy.categories:
        return (
            '"unclassified" — no tenant-specific category taxonomy is '
            "configured; always use this value."
        )
    lines = [
        f'"{c.id}" — {c.description}' for c in taxonomy.categories
    ]
    lines.append(
        '"unclassified" — use only if the ticket does not match any of the '
        "categories above."
    )
    return "\n".join(lines)
```

The output-schema description (line 1256, `"category": list(_CATEGORY_VALUES)`)
becomes `"category": [c.id for c in taxonomy.categories] + ["unclassified"]` —
still an explicit enumerated list in the prompt (good for LLM steerability), just
**tenant-sourced** instead of module-constant.

### 4.3 Validation change — `_parse_output` (lines 971-998)

Today, Pydantic's `DiagnosticCategory` enum rejects unknown values *during
deserialization*, before `_parse_output` returns. With `category: str`, parsing
always succeeds (any non-empty ≤200-char string). **Taxonomy-membership
validation moves to a new explicit step**, run immediately after `_parse_output`
in `DiagnosticCognitionRuntime.reason_about_ticket` (or equivalent):

```python
def _validated_category(
    raw_category: str, taxonomy: ResolutionTaxonomyPolicy,
) -> str:
    if not taxonomy.categories:
        return "unclassified"
    if raw_category in taxonomy.category_ids():
        return raw_category
    logger.warning(
        "diagnostic_category_outside_tenant_taxonomy",
        extra={"raw_category": raw_category},
    )
    return "unclassified"
```

This is **fail-closed and non-fatal**: an LLM that ignores the prompt and returns
an out-of-taxonomy string does not crash the diagnostic stage (today's behavior on
enum-mismatch is a parse exception → retry/failure path, which is *more* disruptive
than necessary for what is, after this change, a recoverable situation) — it
degrades to `"unclassified"`, which (§3.4) guarantees human review. The raw LLM
output is preserved in `diagnostic_summary`/forensics for operator visibility, only
`category` is clamped.

### 4.4 New plumbing requirement: taxonomy must reach the diagnostic stage

`DiagnosticCognitionRuntime.__init__` (`diagnostic_runtime.py:172-195`) does not
currently receive a `TenantConfigurationRepository`. It needs one (or a
pre-resolved `ResolutionTaxonomyPolicy`) to render the prompt (§4.2). Two options:

- **(a)** Pass `TenantConfigurationRepository` into
  `DiagnosticCognitionRuntime.__init__`, resolve `ResolutionTaxonomyPolicy` inside
  `reason_about_ticket` (one extra DB read per diagnostic execution, same pattern
  as `resolve_resolution_autonomy_policy` in `ResolutionRuntime`).
- **(b)** Resolve the taxonomy once in `agent_tasks.py`
  (`_generate_diagnostic_reasoning_for_work_item` /
  `_load_diagnostic_reasoning_snapshot`, which already runs inside a DB session)
  and pass the resolved `ResolutionTaxonomyPolicy` into
  `reason_about_ticket(...)` as a parameter — no constructor change to
  `DiagnosticCognitionRuntime`, but the snapshot/dataclasses that carry prompt
  inputs gain a field.

**Recommendation: (b)** — keeps `DiagnosticCognitionRuntime` free of a repository
dependency (consistent with it currently being LLM/knowledge-focused, not
tenant-config-focused), and reuses the call site
(`_append_resolution_proposal_after_diagnostic`, agent_tasks.py:1687) which
*already* constructs a `PostgresTenantConfigurationRepository` for the resolution
stage — except taxonomy resolution must happen **before** the diagnostic LLM call,
i.e. earlier in the pipeline than where that repository is currently constructed.
Concretely: `_load_diagnostic_reasoning_snapshot` (line 805) needs the same
repository constructed earlier and threaded through
`DiagnosticReasoningSnapshot` (add a `resolved_taxonomy: ResolutionTaxonomyPolicy`
field) so `_render_system_prompt` can use it when building `snapshot.system_prompt`.

This is the single largest structural change in this spec — flagged explicitly so
reviewers can push back on it before Step 2 begins.

## 5. `_resolution_category()` becomes a thin pass-through

```python
def _resolution_category(
    *,
    diagnostic_category: str,
    taxonomy: ResolutionTaxonomyPolicy,
) -> str:
    if diagnostic_category == "unclassified":
        return "unclassified"
    if diagnostic_category in taxonomy.category_ids():
        return diagnostic_category
    # Defense-in-depth: diagnostic stage already clamps to "unclassified"
    # (§4.3), but a future caller that skips that step must not silently
    # adopt an unvalidated category string.
    return "unclassified"
```

- `original_content` parameter is **removed** — no more keyword reclassification.
- All English-keyword branches (`"warranty"`/`"refund"`/`"charging"`/etc., lines
  689-698) are **deleted**, not relocated. They were the electronics-specific
  reclassifier this whole spec exists to remove.
- `ResolutionRuntime.create_proposal` (resolution_runtime.py:252-255) resolves
  `ResolutionTaxonomyPolicy` (same `tenant_configuration_repository` already
  threaded for `resolution_autonomy`, §2 of the 2026-06-12 spec) and passes it
  here instead of `original_content`.

## 6. `_recommended_actions()` becomes a taxonomy lookup

```python
def _recommended_actions(
    category: str, taxonomy: ResolutionTaxonomyPolicy,
) -> tuple[Mapping[str, Any], ...]:
    return taxonomy.actions_for(category)
```

(`actions_for`, §3.3, already returns the collect-context fallback for any
category not present in `taxonomy.categories` — including `"unclassified"`.) The
entire hardcoded table (resolution_runtime.py:702-829: `charging_issue`,
`product_defect`, `refund_requested`, `warranty_replacement_inquiry`,
`returns_refunds_inquiry`) is **deleted**.

**Restated invariant from the 2026-06-12 spec, unchanged:** `recommended_actions`
with `requires_execution: true` are *recorded*, never *executed*, by this code
path. Execution still requires `TenantActionPolicy.evaluate()`
(`app/agents/tools/action_governance.py`) at `EnforcementStage.PRE_EXECUTION`,
under `policy_type="action_tools"` — **completely untouched by this spec**. The
only thing tenant-defined now is *which* `tool_name` a category's
`requires_execution: true` action references (§3.2's registry-membership check
ensures it's always a tool `action_governance.py` already knows how to gate) —
not whether that gate runs, or what its rules are.

## 7. Monetary-commitment guard generalization

### 7.1 `_monetary_commitment_exceeds_threshold` — domain-agnostic detector + tenant vocab

Current (resolution_runtime.py:941-951):

```python
def _monetary_commitment_exceeds_threshold(text: str, threshold_cents: int) -> bool:
    if not _contains_any(text, ("refund", "replacement", "replace", "warranty")):
        return False
    for match in _MONEY_PATTERN.finditer(text):
        ...
```

New:

```python
def _monetary_commitment_exceeds_threshold(
    text: str, threshold_cents: int, taxonomy: ResolutionTaxonomyPolicy,
) -> bool:
    money_pattern = _money_pattern_for(taxonomy)
    for match in money_pattern.finditer(text):
        amount_text = match.group("prefix") or match.group("suffix")
        if amount_text is None:
            continue
        amount_cents = round(float(amount_text.replace(",", "")) * 100)
        if amount_cents >= threshold_cents:
            return True
    return False
```

**Key change: the `_contains_any(text, ("refund", ...))` pre-condition is
removed.** *Any* detected monetary amount in a generated reply — regardless of
surrounding vocabulary — is now subject to the threshold check. This is the
"domain-agnostic monetary-commitment detector" from goal 4: it requires zero
tenant configuration to be *safe* for a non-electronics tenant (previously such a
tenant's money-mentioning replies were never checked at all — "inert" per the
2026-06-12 spec's §6; now they're checked using the tenant's
`monetary_commitment_threshold_cents`, which defaults to `0`, i.e. *any* amount ≥
$0 triggers approval — maximally conservative for an unconfigured tenant).

`tenant.monetary_commitment.remedy_keywords` (§3.2) is **not** used by this
function — it exists for tenants who want `_UNSUPPORTED_PROMISE_PATTERNS`-style
hard-deny coverage of *commitment phrases without a dollar figure* (§7.2), where
"refund"-style words still matter because there's no number to anchor on.

`_money_pattern_for(taxonomy)` builds a regex from
`taxonomy.monetary_currency_symbols ∪ {"$"}` and
`taxonomy.monetary_currency_codes ∪ {"usd", "dollars"}` (defaults per §3.5 already
include `$`/`usd`/`dollars`, so the `∪` is redundant for the default case but
makes explicit that tenant-added symbols are *additive*, never replacing the
USD baseline — backward compatible by construction).

### 7.2 `_UNSUPPORTED_PROMISE_PATTERNS` → tenant-configured, additive

```python
def _unsupported_commitment_patterns(
    taxonomy: ResolutionTaxonomyPolicy,
) -> frozenset[str]:
    return _BASELINE_UNSUPPORTED_PROMISE_PATTERNS | taxonomy.unsupported_commitment_patterns
```

`_BASELINE_UNSUPPORTED_PROMISE_PATTERNS` (the existing module constant, lines
109-122 — `"we will refund"`, `"covered under warranty"`, etc.) **stays as a
hardcoded baseline**, not because it's domain-agnostic (it isn't), but because:

- It is *purely additive* to the deny check — a non-electronics tenant's replies
  will simply never match these English e-commerce phrases, so the baseline is
  inert-but-harmless for them (same "safe but inert" characterization the
  2026-06-12 spec gave the pre-existing remedy-keyword check).
- Removing it would be a **silent behavior change** for the live-test tenant
  (loses an existing DENY path) with no corresponding tenant-config migration step
  — worse than leaving a harmless-for-others baseline in place.
- A tenant in another domain adds *their own* domain-specific unsupported-promise
  phrases via `unsupported_commitment_patterns` (§3.2) — e.g. a bank tenant adds
  `"we will reverse the charge"`, `"guaranteed dispute win"`.

This is the one place this spec keeps a hardcoded, English, domain-shaped
constant — explicitly justified above as inert-for-others/baseline-only, and
called out in §10's confirmations.

### 7.3 Threading taxonomy into `_evaluate_gate`

```python
def _evaluate_gate(
    *,
    category: str,
    reply: str,
    evidence: tuple[Mapping[str, Any], ...],
    autonomy_policy: ResolutionAutonomyPolicy,
    taxonomy: ResolutionTaxonomyPolicy,
) -> _GateDecision:
    ...
    if _monetary_commitment_exceeds_threshold(
        text, autonomy_policy.monetary_commitment_threshold_cents, taxonomy,
    ):
        reasons.append("monetary_commitment_requires_approval")
    ...
    if _contains_any(
        reply.lower(), _unsupported_commitment_patterns(taxonomy),
    ):
        return _GateDecision(..., reasons=("unsupported_commitment_promise",), ...)
```

`original_content` is no longer needed for category derivation (§5) but is still
used to build `text = f"{original_content} {reply}".lower()` for the
safety/legal/fraud keyword screens (`_SAFETY_KEYWORDS` etc., lines 57-108) —
**those are unchanged by this spec** (not in the user's enumerated hardcoding
list; flagged as a *further* residual item in §9 for completeness, since
"injury"/"explosion"/"swollen battery" are also electronics-shaped, but the user's
scope here is taxonomy/actions/remedy-vocab specifically).

## 8. Migration / config shape for the existing live-test tenant (`anker-pilot`)

To retain current behavior, `anker-pilot` needs **both**:

1. A `resolution_taxonomy` policy reproducing today's five reachable categories
   (`charging_issue`, `product_defect`, `refund_requested`,
   `warranty_replacement_inquiry`, `returns_refunds_inquiry`) plus their existing
   `_recommended_actions()` tables verbatim as `recommended_actions` arrays, and
   `monetary_commitment.remedy_keywords` left empty (the new domain-agnostic
   detector, §7.1, supersedes the old `("refund","replacement","replace","warranty")`
   pre-condition — no tenant config needed to reproduce *at least as much*
   coverage as before).
2. The `resolution_autonomy` policy (already configured per the 2026-06-12
   spec / the prior change-request task) with `category_allowlist` values that
   are a subset of (1)'s category ids — validated by §3.4's cross-check.

Until (1) is configured, `anker-pilot`'s diagnostic stage emits `"unclassified"`
for everything (§4.3, since `taxonomy.categories` is empty), `_recommended_actions`
returns only the collect-context fallback, and (per the already-shipped
`resolution_autonomy` fail-closed behavior) every proposal requires human
approval — **strictly more conservative than today**, exactly the same shape of
transition the 2026-06-12 spec already executed for `resolution_autonomy` itself.
This is a second, additive "configure or lose auto-send" migration step for the
same tenant.

## 9. Residual gaps (explicitly out of scope, for future follow-up)

- `_SAFETY_KEYWORDS`, `_LEGAL_KEYWORDS`, `_FRAUD_KEYWORDS`, `_POLICY_EXCEPTION_KEYWORDS`
  (resolution_runtime.py:57-108) remain hardcoded English/electronics-leaning
  vocab (`"swollen battery"`, etc.). Same "safe but possibly incomplete for other
  domains" characterization as §7.2's baseline — not in this spec's enumerated
  scope, flagged for a future spec.
- `_BASELINE_UNSUPPORTED_PROMISE_PATTERNS` (§7.2) remains a hardcoded English
  baseline by design (additive only).
- Per-category `description` strings (§3.2) are injected into the diagnostic
  prompt verbatim — a tenant with a poorly-written description gets poor
  classification accuracy. This is a content-quality concern, not a
  tenant-agnosticism concern, and is out of scope (same way a tenant's knowledge
  base content quality is out of scope for the grounding mechanism).
- Multi-language taxonomy: `label`/`description` are single-string fields. A
  tenant operating in multiple `source_language`s gets an English (or
  whatever-language) taxonomy description used for all languages' diagnostic
  prompts. The existing translation runtime (`EgressLocalizeRequest`) localizes
  *replies*, not the diagnostic *prompt*. Flagged, not addressed.

## 10. Explicit confirmations requested

1. **Zero domain-specific *values* remain hardcoded in category/action/remedy
   logic that this spec touches.** `DiagnosticCategory` enum (deleted),
   `_resolution_category()`'s keyword branches (deleted),
   `_recommended_actions()`'s hardcoded table (deleted), and the
   `_contains_any(text, ("refund",...))` precondition (deleted) are all removed.
   The two remaining hardcoded constants —
   `_BASELINE_UNSUPPORTED_PROMISE_PATTERNS` (§7.2) and the
   `_SAFETY_/_LEGAL_/_FRAUD_/_POLICY_EXCEPTION_KEYWORDS` sets (§9, untouched) —
   are both *additive baselines* that are inert (never match) for a tenant whose
   domain doesn't use that vocabulary, never *required* for a tenant's
   taxonomy/autonomy to function, and never *block* a tenant from adding their own
   domain-specific patterns (§3.2, `unsupported_commitment_patterns`).
2. **Default (no `resolution_taxonomy` policy) is fail-closed and uses zero
   domain-specific category names.** The only category ever produced is the
   reserved sentinel `"unclassified"` (§3.4), which is structurally guaranteed
   (validation-time rejection of `"unclassified"` as a tenant-declared id, plus
   the cross-policy `category_allowlist` check) to never auto-send or execute an
   action, regardless of any other tenant configuration.
3. **The executable-action gate (`TenantActionPolicy`, `policy_type=
   "action_tools"`, `EnforcementStage.PRE_EXECUTION`) is not modified.** This spec's
   only interaction with it is a **read-only validation reference**
   (§3.2: a tenant's `tool_name` must name a tool `action_governance.py` already
   knows) at policy-*propose* time — no runtime behavior of
   `action_governance.py` changes.
4. **A non-electronics taxonomy (e.g. banking: `disputed_transaction`,
   `card_lost`) classifies and routes correctly with zero electronics
   assumptions in the path** — this is the load-bearing claim, verified by
   §11's break-control test.

## 11. Test / break-control plan

### New unit tests — `tests/test_resolution_taxonomy_policy.py`

- `parse_resolution_taxonomy_policy`: valid parameters → correct
  `ResolutionTaxonomyPolicy`; empty `categories` → raises; duplicate category
  `id` → raises; category `id == "unclassified"` → raises; `requires_execution:
  true` action with unknown `tool_name` → raises; `requires_execution: true`
  action missing `tool_name`/`payload_template`/`target_resource_id` → raises;
  `requires_execution: false` action *with* `tool_name` present → raises;
  `monetary_commitment` absent → defaults per §3.5 table.
- `resolve_resolution_taxonomy_policy`: `repository=None` / no active record /
  invalid record → all return empty policy (`categories=()`).

### Modified unit tests — `tests/test_resolution_runtime.py`

- `_resolution_category`: now takes `(diagnostic_category, taxonomy)`. Test:
  `diagnostic_category="charging_issue"`, taxonomy declares `"charging_issue"` →
  returns `"charging_issue"`. `diagnostic_category="unclassified"` → returns
  `"unclassified"` regardless of taxonomy. `diagnostic_category="some_category"`
  not in taxonomy → returns `"unclassified"` (defense-in-depth case).
- `_recommended_actions`: now `taxonomy.actions_for(category)`. Test: category
  present in taxonomy → returns its configured actions verbatim (including
  `requires_execution: true` entries with tenant-supplied `tool_name`). Category
  absent (including `"unclassified"`) → returns
  `(_COLLECT_CONTEXT_FALLBACK_ACTION,)`.
- `_monetary_commitment_exceeds_threshold`: now `(text, threshold_cents,
  taxonomy)`. Test: text contains `"$200 something"` with **no** "refund"/
  "warranty" word, `threshold_cents=5000`, empty taxonomy → returns `True`
  (previously: `False`, the "inert" case this spec fixes). Test: tenant-added
  `currency_symbols=["€"]`, text contains `"€200"`, → detected.
- `_unsupported_commitment_patterns`: baseline ∪ tenant patterns; tenant-only
  pattern (e.g. `"we will reverse the charge"`) matches when present in
  `taxonomy.unsupported_commitment_patterns`, does not match for a tenant that
  didn't configure it.

### Modified unit tests — `tests/test_grounding_acknowledgment_classification.py` and diagnostic tests

- `DiagnosticLLMOutput.category` accepts arbitrary non-empty strings ≤200 chars;
  rejects empty string and >200 chars.
- `_render_system_prompt(source_language, taxonomy=...)`: empty taxonomy →
  prompt instructs "always use `unclassified`"; non-empty taxonomy → prompt lists
  each `id`/`description` plus `"unclassified"` as the fallback.
- `_validated_category`: in-taxonomy raw category → passthrough; out-of-taxonomy
  raw category → `"unclassified"` + warning log, no exception.

### LOAD-BEARING break-control test: banking taxonomy, zero electronics assumptions

**Setup:**

- `resolution_taxonomy` policy for tenant `bank-pilot`:
  - `categories`: `disputed_transaction` (with `recommended_actions` including a
    `requires_execution: true` action with `tool_name` referencing a
    *registered* dispute-handling tool — substitute an existing registry tool
    name for the test, e.g. reuse `"refund.request"` from the existing registry
    as a stand-in "reversal" tool if no bank-specific tool exists yet, OR add a
    test-only registered tool — implementation detail for Step 2) and `card_lost`
    (no `requires_execution: true` actions, to also cover the
    advisory-only path).
  - `monetary_commitment.remedy_keywords = []`, `currency_symbols = []`,
    `currency_codes = []` (i.e. bank tenant configures *nothing* extra — relies
    purely on the domain-agnostic `$`/`usd`/`dollars` default + the new
    no-precondition detector).
  - `unsupported_commitment_patterns = ["we will reverse the charge"]`.
- `resolution_autonomy` policy: `category_allowlist = ["card_lost"]`,
  `monetary_commitment_threshold_cents = 0`.
- Diagnostic input ticket text: "Someone made a $340 charge on my account that I
  didn't authorize." — contains zero electronics vocabulary (no "battery",
  "charging", "warranty", "device", etc. in any sense that would trigger the
  *old* `_resolution_category()` keyword branches, **except** the substring
  "charge" — which is exactly why this test is load-bearing: the old
  `_resolution_category()` would match `"charge"` via its `("charge", "charging",
  "charger", "battery", "power")` tuple at line 693 and misclassify this as
  `"charging_issue"`).

**Assertions:**

1. Diagnostic LLM (stubbed/fake client in the test, returning
   `category="disputed_transaction"`) → `_validated_category` returns
   `"disputed_transaction"` (in `bank-pilot`'s taxonomy).
2. `_resolution_category(diagnostic_category="disputed_transaction",
   taxonomy=bank_taxonomy)` returns `"disputed_transaction"` — **not**
   `"charging_issue"`. This is the regression the old keyword-matcher would cause
   (the word "charge" appears in the ticket text) — demonstrating it with the old
   code (run as a "control" sub-test against the *current* `_resolution_category`
   signature, expected to fail/return `"charging_issue"`) and the new code
   (expected to return `"disputed_transaction"`) is the actual break-control pair.
3. `_recommended_actions("disputed_transaction", bank_taxonomy)` returns the
   bank-configured actions, including the `requires_execution: true` dispute
   action with the bank's `tool_name`/`payload_template` — **not** any of
   `warranty.claim`/`refund.request`/`warehouse.repair.report`'s hardcoded
   electronics payload shapes (`product_sku`, `order_id`, etc. do not appear
   unless the bank's `payload_template` happens to include them, which it
   doesn't).
4. `_evaluate_gate(category="disputed_transaction", ...)`: since
   `"disputed_transaction" not in autonomy_policy.reply_auto_send_categories`
   (only `"card_lost"` is allowlisted), gate reason is `"unsupported_auto_category"`,
   status `PENDING_HUMAN_APPROVAL` — correct tenant-configured behavior, not a
   fallback artifact.
5. Separately, a `card_lost` proposal (allowlisted) with reply text "We've blocked
   your card; a replacement will arrive in 5 business days." (no dollar amount, no
   `unsupported_commitment_patterns` match) → `AUTO_APPROVED` / `SEND_ELIGIBLE`
   (after central gate). This proves the *positive* path: a non-electronics
   category can reach auto-send when properly configured — the whole pipeline
   (diagnostic classification → taxonomy lookup → autonomy allowlist → central
   gate) works end-to-end for a domain with zero electronics categories declared
   anywhere in its `resolution_taxonomy`.

### CI

- `pyright` (0 errors — note `DiagnosticCategory` deletion requires updating all
  references found by a repo-wide grep before this is type-clean), `ruff`,
  invariant + forbidden-dependency suites, full `apps/backend/tests` run from repo
  root.

## 12. Open items for implementation (Step 2)

- Resolve §4.4's plumbing question concretely: trace
  `_load_diagnostic_reasoning_snapshot` → `_complete_diagnostic_reasoning_snapshot`
  → `DiagnosticCognitionRuntime.reason_about_ticket` call chain and determine the
  minimal-diff way to thread a resolved `ResolutionTaxonomyPolicy` through
  `DiagnosticReasoningSnapshot`.
- Repo-wide grep for `DiagnosticCategory` usages (tests, fixtures, any
  serialization/migration code) before deletion — confirm the "exactly one
  production reference" claim in §4.1 and enumerate test-only references that
  need updating.
- Confirm the action-tool registry module/constant to use for §3.2's `tool_name`
  validation (`_DISPATCH_TOOL_NAMES` in `action_governance.py` vs. the broader
  registry in `app/agents/tools/actions/__init__.py` — determine which is the
  authoritative "known tool names" set for policy-time validation, since
  `_DISPATCH_TOOL_NAMES` appeared to be a subset used for dispatch-specific
  rules).
- Confirm per-category `description` length cap (§3.2) and total taxonomy prompt
  size budget given existing prompt-size constraints in
  `diagnostic_runtime.py`.
- Add `_validate_resolution_taxonomy_policy_payload` to
  `tenant_config_change_request_service.py` (mirrors
  `_validate_resolution_autonomy_policy_payload`), plus the §3.4 cross-policy
  `category_allowlist ⊆ taxonomy.category_ids()` check in the
  `resolution_autonomy` payload validator (bidirectional: also re-validate
  `resolution_autonomy` if a `resolution_taxonomy` change is applied that would
  shrink `category_ids()` below the existing allowlist — or accept that as a
  config-drift risk documented for operators, to be decided in Step 2).
- `InMemoryTenantConfigurationRepository` test fixture needs `resolution_taxonomy`
  records seedable the same way `resolution_autonomy` records are (per the
  2026-06-12 spec's §10, this should already be generic over `policy_type`).
