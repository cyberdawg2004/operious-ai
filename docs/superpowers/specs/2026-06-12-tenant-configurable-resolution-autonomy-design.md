# Tenant-Configurable Resolution Autonomy (Phase 2.2)

- **Date:** 2026-06-12
- **Status:** Draft — awaiting approval
- **Sub-project:** Customer support autonomy — governance gate hardening
- **Owner:** backend

## 1. Context and problem

Operious is tenant-agnostic infrastructure: a given tenant (e.g. an electronics brand) is a
live-test harness, not the product. Nothing about *which reply categories may auto-send* or
*what counts as a high-value commitment requiring human approval* may be baked into module-
level constants — that is per-tenant policy, set at onboarding.

Today two files each define a hardcoded, domain-shaped `_SAFE_AUTO_CATEGORIES` frozenset:

- `app/runtime/resolution_runtime.py:52-59` (local gate, `_evaluate_gate`)
- `app/runtime/resolution_governance_gate.py:48-64` (central gate,
  `ResolutionCommunicationPolicy._approval_rule`, plus a second frozenset
  `_REQUIRES_APPROVAL_CATEGORY_TOKENS`)

Both lists contain category names that only make sense for an electronics-warranty tenant
(`charging_issue`, `connectivity_issue`, `power_issue`, `warranty`/`refund`/`replacement`
tokens). A reverted, uncommitted change (see Step 0) attempted to widen autonomy by adding
two more hardcoded categories to one of these lists *and* deleting
`_high_value_refund_or_replacement` — a content-based money-guard
(`app/runtime/resolution_runtime.py`, pre-revert lines ~849-944) that forces human review
when a reply text mentions a refund/replacement/warranty alongside a dollar amount ≥ $100.
Deleting that guard removed the only safety net on what an auto-sent reply can *promise*,
independent of whether the linked execution action (`warranty.claim`, `refund.request`,
which have `requires_execution: true`) is itself gated.

This spec replaces both hardcoded category lists with **per-tenant configuration**, read
through the existing governance-policy mechanism, and replaces the deleted money-guard with
a **per-tenant, conservative-by-default monetary-commitment threshold** — restoring the
safety property the reverted change removed, but as configuration instead of a hardcoded
`$100` / hardcoded category list.

## 2. Survey of existing config surfaces

`app/agents/tools/action_governance.py` already establishes the right pattern for "tenant
declares thresholds, code reads them, fail-closed if absent":

- `TenantActionPolicy` (a `BaseGovernancePolicy`) loads a `TenantGovernancePolicyRecord` via
  `TenantConfigurationRepository.resolve_active_governance_policy(policy_type="action_tools",
  expected_tenant_id=...)`.
- If no active record exists, every action tool call is **denied** (`_deny("no active
  'action_tools' policy for tenant", ...)`) — fail-closed by construction.
- Parameters are an arbitrary JSON `Mapping` on `TenantGovernancePolicyRecord.parameters`,
  parsed by `parse_action_tools_policy` / validated by
  `validate_action_tools_policy_parameters` (raises `ActionPolicyParseError` on malformed
  input). `WarrantyRule.confidence_gte`, `RefundRule.refund_amount_cents_lte`, etc. are the
  existing per-tenant thresholds for *executable* actions.
- Storage: `tenant_governance_policies` table (migration `0014`), generic
  `(tenant_id, policy_type, parameters jsonb, status, version, ...)` — **no schema change
  needed** for a new `policy_type`. The change-request approval workflow
  (`app/services/tenant_config_change_request_service.py`) already handles arbitrary
  `policy_type` values for `TenantConfigChangeType.POLICY`; it special-cases
  `action_tools` for extra validation (`_validate_action_policy_payload`,
  line 857-873) and falls through to generic `(policy_type, effective_from)` validation for
  everything else.

This is the **minimal, consistent home** for resolution-autonomy config: a new
`policy_type = "resolution_autonomy"` governance policy, same table, same approval
workflow, same fail-closed-when-absent posture as `action_tools`.

## 3. New policy type: `resolution_autonomy`

New module `app/runtime/resolution_autonomy_policy.py`, mirroring the structure of
`action_governance.py`'s parsing layer (but *not* a `BaseGovernancePolicy` itself — it's a
plain parser/lookup used by both the local gate and the central
`ResolutionCommunicationPolicy`, see §4).

```python
ACTION_TOOLS_POLICY_TYPE = "action_tools"          # existing, unchanged
RESOLUTION_AUTONOMY_POLICY_TYPE = "resolution_autonomy"  # new


@dataclass(frozen=True, slots=True)
class ResolutionAutonomyPolicy:
    reply_auto_send_categories: frozenset[str]
    monetary_commitment_threshold_cents: int


class ResolutionAutonomyPolicyParseError(ValueError):
    """Raised when a tenant's resolution_autonomy policy JSON is malformed."""


def parse_resolution_autonomy_policy(
    record: TenantGovernancePolicyRecord,
) -> ResolutionAutonomyPolicy: ...


def validate_resolution_autonomy_policy_parameters(
    parameters: Mapping[str, Any],
) -> None: ...


async def resolve_resolution_autonomy_policy(
    *,
    repository: TenantConfigurationRepository | None,
    tenant_id: str,
) -> ResolutionAutonomyPolicy:
    """Fail-closed: returns the empty/zero-threshold policy if repository is
    None, no active record exists, or the record fails to parse."""
```

### Parameters JSON shape

```json
{
  "_schema_version": "1",
  "policy_type": "resolution_autonomy",
  "parameters": {
    "reply_auto_send": {
      "category_allowlist": ["charging_issue", "generic_troubleshooting"],
      "monetary_commitment_threshold_cents": 10000
    }
  }
}
```

- `category_allowlist`: non-empty list of opaque strings (validated the same way
  `_require_string_set` validates `issue_category_in` in `action_governance.py`) — **no
  enumeration of allowed values in code**. Whatever strings the tenant puts here are
  compared against whatever string `_resolution_category()` produces for a given proposal
  (see §6 for the residual issue this doesn't solve).
- `monetary_commitment_threshold_cents`: non-negative integer, **optional, defaults to
  `0`** if omitted. `0` means "any detected dollar amount in a reply that mentions a
  remedy commitment forces human review" — the most conservative possible value, so an
  incomplete config never accidentally widens autonomy.

### `resolve_resolution_autonomy_policy` fail-closed table

| Condition | Result |
|---|---|
| `repository is None` | `ResolutionAutonomyPolicy(frozenset(), 0)` |
| no active `resolution_autonomy` record for tenant | `ResolutionAutonomyPolicy(frozenset(), 0)` |
| record exists but fails to parse (`ResolutionAutonomyPolicyParseError`) | `ResolutionAutonomyPolicy(frozenset(), 0)`, logged as `resolution_autonomy_policy_invalid` |
| record exists and parses | the parsed policy |

An empty `category_allowlist` means **every** category falls through to
`"resolution_category_not_auto_safe"` / `"unsupported_auto_category"` (existing reason
strings, unchanged) — i.e. require approval. This is exactly today's behavior for any
tenant that has never configured `resolution_autonomy`: identical to pre-change behavior
for categories not in the old hardcoded `_SAFE_AUTO_CATEGORIES`, and *more* conservative
than pre-change behavior for categories that *were* in the old hardcoded set (those tenants
must now explicitly configure the allowlist — see §7 backward-compat).

## 4. Wiring into the two gates

### 4a. Local gate — `app/runtime/resolution_runtime.py`

`_evaluate_gate` currently takes no tenant-config input. It becomes:

```python
def _evaluate_gate(
    *,
    category: str,
    original_content: str,
    reply: str,
    evidence: tuple[Mapping[str, Any], ...],
    autonomy_policy: ResolutionAutonomyPolicy,
) -> _GateDecision:
    ...
    if _monetary_commitment_exceeds_threshold(
        text, autonomy_policy.monetary_commitment_threshold_cents
    ):
        reasons.append("monetary_commitment_requires_approval")
    ...
    if reasons or category not in autonomy_policy.reply_auto_send_categories:
        return _GateDecision(..., reasons=tuple(reasons or ("unsupported_auto_category",)))
    ...
```

`_high_value_refund_or_replacement` (the deleted function) is restored as
`_monetary_commitment_exceeds_threshold(text, threshold_cents)`, reusing the existing
`_MONEY_PATTERN` regex and the existing remedy-keyword check
(`refund`/`replacement`/`replace`/`warranty`) — **only the hardcoded `>= 100` USD constant
is replaced** by `>= threshold_cents / 100`. (The remedy-keyword vocabulary itself is a
smaller residual issue, flagged in §6 — it is not new hardcoding introduced by this change,
it is the *pre-existing* vocabulary from the function this spec restores.)

`ResolutionRuntime.create_proposal` resolves the policy once per proposal and threads it
through:

```python
autonomy_policy = await resolve_resolution_autonomy_policy(
    repository=self._tenant_configuration_repository,
    tenant_id=request.tenant_id,
)
gate = _evaluate_gate(
    category=category,
    original_content=request.original_content,
    reply=reply,
    evidence=evidence,
    autonomy_policy=autonomy_policy,
)
```

`ResolutionRuntime.__init__` gains a new keyword-only parameter:

```python
def __init__(
    self,
    *,
    persistence: ResolutionProposalPersistenceProtocol,
    governance_gate: ResolutionGovernanceGateProtocol | None = None,
    conversation_generator: ConversationGenerationRuntimeProtocol | None = None,
    tenant_configuration_repository: TenantConfigurationRepository | None = None,
    auto_approve_threshold: float = _DEFAULT_AUTO_APPROVE_THRESHOLD,
) -> None:
```

Defaulting to `None` is **fail-closed, not a compatibility shim**: per §3's table, `None`
resolves to `ResolutionAutonomyPolicy(frozenset(), 0)`, so any caller that doesn't pass a
repository gets the most conservative behavior (nothing auto-sends), not the old hardcoded
allowlist. Existing tests that construct `ResolutionRuntime` without this argument continue
to pass — they currently exercise categories outside the relevant paths, or assert
`PENDING_HUMAN_APPROVAL`, which is the codepath now reached unconditionally for any tenant
without config (see test inventory in §8).

### 4b. Central gate — `app/runtime/resolution_governance_gate.py`

`ResolutionCommunicationPolicy` is currently stateless (no `__init__`). It gains a
constructor and the policy lookup:

```python
class ResolutionCommunicationPolicy(BaseGovernancePolicy):
    def __init__(
        self,
        *,
        tenant_configuration_repository: TenantConfigurationRepository | None = None,
    ) -> None:
        self._repository = tenant_configuration_repository

    async def evaluate(self, context: GovernanceContext) -> Sequence[PolicyEvaluationResult]:
        ...
        autonomy_policy = await resolve_resolution_autonomy_policy(
            repository=self._repository,
            tenant_id=subject.tenant_id,
        )
        approval_rule = _approval_rule(
            category=category,
            local_status=local_status,
            local_autonomy=local_autonomy,
            local_governance=...,
            local_supervisor=...,
            autonomy_policy=autonomy_policy,
        )
```

`_approval_rule` drops `_SAFE_AUTO_CATEGORIES`, `_REQUIRES_APPROVAL_CATEGORY_TOKENS`, and
`_category_requires_approval` entirely:

```python
def _approval_rule(
    *,
    category: str,
    local_status: str,
    local_autonomy: str,
    local_governance: str | None,
    local_supervisor: str | None,
    autonomy_policy: ResolutionAutonomyPolicy,
) -> str | None:
    if local_status != "auto_approved":
        return "local_status_not_auto_approved"
    if local_autonomy != "auto_approved":
        return "local_autonomy_not_auto_approved"
    if local_governance != "allow":
        return "local_governance_not_allow"
    if local_supervisor != "pass":
        return "local_supervisor_not_pass"
    if category not in autonomy_policy.reply_auto_send_categories:
        return "resolution_category_not_auto_safe"
    return None
```

Note the central gate **only re-derives `reasons=tuple(...)`** state machine outcome — it
does not re-run the monetary-commitment text scan (that's a local-gate-only check on the
generated reply text, §4a). The central gate's category-allowlist check is a second,
independent enforcement of the same tenant config, so a bug in the local gate alone cannot
widen autonomy — both gates must agree.

`build_resolution_governance_runtime` gains the same keyword-only parameter and threads it
to `ResolutionCommunicationPolicy`:

```python
def build_resolution_governance_runtime(
    *,
    persistence: BaseGovernanceRepository | None = None,
    grounding_checker: GroundingChecker | None = None,
    tenant_configuration_repository: TenantConfigurationRepository | None = None,
) -> GovernanceRuntime:
    ...
    policies=(
        ResolutionCommunicationPolicy(
            tenant_configuration_repository=tenant_configuration_repository,
        ),
        GroundingPolicy(checker=grounding_checker),
    ),
```

### 4c. Call-site wiring — `app/workers/agent_tasks.py:1701-1721`

The call site already constructs a `PostgresTenantConfigurationRepository` for the
grounding checker (line ~1710). Reuse the same instance for both new parameters:

```python
tenant_configuration_repository = PostgresTenantConfigurationRepository(
    session, data_protection=data_protection,
)
proposal = await ResolutionRuntime(
    persistence=resolution_persistence,
    governance_gate=ResolutionGovernanceGate(
        governance_runtime=build_resolution_governance_runtime(
            persistence=governance_repo,
            grounding_checker=CitationCoverageGroundingChecker(
                document_repository=tenant_configuration_repository,
            ),
            tenant_configuration_repository=tenant_configuration_repository,
        )
    ),
    conversation_generator=GroundedConversationGenerationRuntime(
        llm_client=_diagnostic_llm_client()
    ),
    tenant_configuration_repository=tenant_configuration_repository,
).create_proposal(...)
```

## 5. The safety invariant (executable actions)

**Stated explicitly, this is the load-bearing property of the whole design:**

> An action with `requires_execution: true` in `_recommended_actions()` (currently
> `warranty.claim`, `refund.request`, `replacement.order`, `warehouse.repair.report`) is
> *only* ever executed after `TenantActionPolicy.evaluate()` (`app/agents/tools/
> action_governance.py`) runs at `EnforcementStage.PRE_EXECUTION` for that specific tool
> call, with its own per-tenant `policy_type="action_tools"` configuration
> (`WarrantyRule.confidence_gte`, `RefundRule.refund_amount_cents_lte`, etc.). This spec
> **does not touch `action_governance.py` or the `action_tools` policy type at all.**

This change only affects:

1. Whether the *reply text* (`customer_reply.send`) is allowed to auto-send
   (`ResolutionAutonomyDecision` / `ResolutionProposalStatus` on the proposal).
2. The `resolution_autonomy.reply_auto_send.category_allowlist` and
   `monetary_commitment_threshold_cents` fields — both purely about the *reply*, never
   about whether `warranty.claim`/`refund.request`/etc. actually execute.

Concretely: `recommended_actions` (with their `requires_execution` flags) are persisted on
the `ResolutionProposalRecord` regardless of the autonomy-config outcome — a
`PENDING_HUMAN_APPROVAL` proposal still records "this would warrant a `warranty.claim`",
for a human reviewer to act on. Widening `reply_auto_send.category_allowlist` for a tenant
**only** lets the *reply* go out without human sign-off; it can never cause
`warranty.claim`/`refund.request`/etc. to skip `TenantActionPolicy`. There is no code path
from `resolution_autonomy` policy parameters into the `action_tools` pre-execution chain —
they are different `policy_type` values resolved by different policy classes
(`ResolutionCommunicationPolicy` vs `TenantActionPolicy`), evaluated in different
`GovernanceRuntime` instances (`build_resolution_governance_runtime` vs
`build_action_tool_governance_runtime`), at different times (proposal creation vs. tool
invocation).

The restored `monetary_commitment_threshold_cents` check is **additional** defense-in-depth
on top of this — it stops an auto-sent reply from *verbally promising* a refund/replacement
above a tenant's comfort threshold, independent of whether the linked execution action would
itself pass `TenantActionPolicy`. It is not a substitute for `TenantActionPolicy` and
`TenantActionPolicy` is not a substitute for it (a reply can promise something even if the
linked action would later be denied — that's the scenario `_UNSUPPORTED_PROMISE_PATTERNS`
already partially covers, and this threshold covers the "promise with a number attached"
variant that doesn't use those exact phrases).

## 6. Residual tenant-agnosticism gaps (out of scope, flagged for follow-up)

Per the framing, it's worth being explicit about what this spec does **not** fix, so it
isn't mistaken for "done":

- **`_resolution_category()`** (`resolution_runtime.py:679-696`) reclassifies the
  diagnostic's category using hardcoded English keyword matches
  (`"warranty"`, `"replacement"`, `"refund"`, `"charge"`/`"battery"`/`"power"`, etc.) to
  produce the category string this spec's `category_allowlist` matches against. This is
  itself domain-shaped (electronics/e-commerce vocabulary, English-only) and pre-existing —
  **not modified by this spec**. A tenant's `category_allowlist` only works correctly today
  if the tenant's issues happen to map onto these keyword buckets. Recommended follow-up: a
  tenant-defined category taxonomy (declared at onboarding, used by the diagnostic
  classifier directly), so `_resolution_category` becomes a thin pass-through of
  `diagnostic_category` rather than a reclassifier.
- **`_recommended_actions()`** (`resolution_runtime.py:699-826`) hardcodes which tool
  (`warranty.claim`, `refund.request`, `warehouse.repair.report`) and payload shape applies
  per category, and is keyed off the same hardcoded category strings as above. Also
  pre-existing, also not modified here.
- **`_UNSUPPORTED_PROMISE_PATTERNS`** and the remedy-keyword vocabulary inside
  `_monetary_commitment_exceeds_threshold` (`"refund"`, `"replace"`, `"warranty"`) remain
  English/e-commerce-shaped. Restoring the function (§4a) preserves this pre-existing
  vocabulary; it does not generalize it. A tenant in, say, healthcare or banking gets a
  monetary-commitment check that simply never fires (no "refund"/"warranty" language in
  their domain) — which is *safe* (fails toward "doesn't trigger an extra approval step
  that doesn't apply"), not unsafe, but it means the guard is currently inert for such
  tenants. Follow-up: tenant-configured remedy-commitment keyword list, analogous to
  `category_allowlist`.

None of these are regressions from this change — they are pre-existing hardcoding this spec
does not touch. They're listed so the reviewer doesn't read "tenant-configurable resolution
autonomy" as "fully tenant-agnostic resolution pipeline."

## 7. Backward compatibility

No tenant has a `resolution_autonomy` governance policy record today (the `policy_type`
doesn't exist yet). Per §3's fail-closed table, every existing tenant resolves to
`ResolutionAutonomyPolicy(frozenset(), 0)` immediately after this ships:

- `category not in frozenset()` is always `True` → every proposal's local gate reason
  becomes `"unsupported_auto_category"` and central gate reason becomes
  `"resolution_category_not_auto_safe"` → every proposal lands in
  `PENDING_HUMAN_APPROVAL`.
- This is **strictly more conservative** than today for the four categories currently in
  the hardcoded `_SAFE_AUTO_CATEGORIES` (`charging_issue`, `generic_troubleshooting`,
  `connectivity_issue`, `power_issue`) — those tenants lose auto-send for those categories
  *until an operator configures `resolution_autonomy` for them*.
- No tenant gains autonomy they didn't have. The only way to get auto-send behavior
  (including reproducing today's behavior for the four currently-safe categories) is an
  explicit `resolution_autonomy` policy change request through the existing approval
  workflow (`TenantConfigChangeType.POLICY`, `policy_type="resolution_autonomy"`).

This is a deliberate, visible behavior change for the live-test tenant (it will need a
`resolution_autonomy` policy configured to retain current auto-send behavior) — consistent
with "autonomy is something a tenant earns and configures, not a default."

## 8. Test / break-control plan

### New unit tests — `tests/test_resolution_autonomy_policy.py`

- `parse_resolution_autonomy_policy`: valid parameters → correct
  `ResolutionAutonomyPolicy`; missing `category_allowlist` → raises
  `ResolutionAutonomyPolicyParseError`; empty `category_allowlist` list → raises (mirrors
  `_require_string_set`'s non-empty requirement); negative
  `monetary_commitment_threshold_cents` → raises; `monetary_commitment_threshold_cents`
  omitted → defaults to `0`.
- `resolve_resolution_autonomy_policy`: `repository=None` → empty policy; no active record
  → empty policy; record present and valid → parsed policy; record present but invalid
  parameters → empty policy (logged).

### Modified unit tests — `tests/test_resolution_runtime.py`

- Existing tests constructing `ResolutionRuntime(...)` without
  `tenant_configuration_repository` must still pass — they currently assert
  `PENDING_HUMAN_APPROVAL`/`NEEDS_HUMAN_APPROVAL` for the categories they exercise (need to
  confirm none of the existing tests assert `AUTO_APPROVED`/`SEND_ELIGIBLE` for one of the
  four previously-hardcoded-safe categories without also providing a repository — if any
  do, they get a fake `TenantConfigurationRepository` with an in-memory
  `resolution_autonomy` record matching the old hardcoded set, added in this same task).
- New test: tenant with `resolution_autonomy.reply_auto_send.category_allowlist =
  ["charging_issue"]` and a `charging_issue` proposal with no monetary commitment in the
  reply → `AUTO_APPROVED` / `SEND_ELIGIBLE` (after central gate also allows).
- New test: same tenant, but reply text contains `"we can offer a $250 replacement"` and
  `monetary_commitment_threshold_cents = 10000` (i.e. $100) → local gate reason
  `"monetary_commitment_requires_approval"`, status `PENDING_HUMAN_APPROVAL`.

### Modified unit tests — `tests/test_resolution_governance_gate.py` (or equivalent)

- `ResolutionCommunicationPolicy` with no `tenant_configuration_repository` and a category
  that was previously in `_SAFE_AUTO_CATEGORIES` → `REQUIRE_APPROVAL` /
  `"resolution_category_not_auto_safe"` (was previously `ALLOW`).
- `ResolutionCommunicationPolicy` with a repository whose `resolution_autonomy` record
  allowlists the proposal's category, and all `local_*` fields green → `ALLOW`.

### LOAD-BEARING break-control test (per Step 1 item 5)

This is the test that proves the restored money-guard actually gates auto-send, and that
the gate cannot be widened by a reply-only config change:

**Setup:** tenant has `resolution_autonomy.reply_auto_send.category_allowlist =
["refund_requested"]` (i.e. this tenant *has* opted reply-auto-send in for this category —
the maximally-permissive config this spec allows for a category whose
`_recommended_actions()` includes a `requires_execution: true` `refund.request`).
`monetary_commitment_threshold_cents = 5000` ($50). Proposal's generated reply text:
`"We can process a $200 refund for your order."` All `local_*` fields green
(supervisor PASS, governance ALLOW, autonomy AUTO_APPROVED would otherwise hold).

- **Intact (PASS):** `_monetary_commitment_exceeds_threshold("... $200 refund ...", 5000)`
  → `True` (20000 cents ≥ 5000 cents) → `_evaluate_gate` appends
  `"monetary_commitment_requires_approval"` to `reasons` → status
  `PENDING_HUMAN_APPROVAL`, regardless of `category_allowlist` membership.
  File:line — `app/runtime/resolution_runtime.py`, the `if reasons or category not in
  autonomy_policy.reply_auto_send_categories:` branch in `_evaluate_gate`.

- **Control removed (DEMONSTRATED-to-FAIL):** comment out the
  `_monetary_commitment_exceeds_threshold(...)` call (i.e. simulate re-deleting the
  money-guard, the original bug). With `category_allowlist` containing
  `"refund_requested"` and no other `reasons`, `_evaluate_gate` now returns
  `AUTO_APPROVED` / `SEND_ELIGIBLE` for a reply that promises a $200 refund — the failing
  assertion is `status == ResolutionProposalStatus.PENDING_HUMAN_APPROVAL`, which becomes
  `SEND_ELIGIBLE`. This demonstrates the exact regression the reverted Step-0 change
  introduced (deleting the money-guard let a category-allowlisted reply auto-send a
  high-value refund promise).

- **Restored (PASS):** re-add the call; test passes again as in "Intact."

### CI

- `pyright` (0 errors), `ruff`, invariant + forbidden-dependency suites, full
  `apps/backend/tests` run from repo root (per existing project convention — running from
  `apps/backend` causes ~29 spurious failures).

## 9. Explicit confirmations requested

1. **No domain/tenant-specific values remain hardcoded in the proposed design.**
   `_SAFE_AUTO_CATEGORIES` (both files) and `_REQUIRES_APPROVAL_CATEGORY_TOKENS` are
   deleted; the only remaining category-name strings are inside `_resolution_category` /
   `_recommended_actions`, which are pre-existing and explicitly flagged as residual (§6),
   not introduced or widened by this change. The new code introduces zero new category
   names, dollar amounts, or category-to-action mappings — `category_allowlist` and
   `monetary_commitment_threshold_cents` are 100% tenant-supplied.
2. **Default is fail-closed.** No `resolution_autonomy` policy record ⇒ empty allowlist ⇒
   every proposal requires human approval (§3, §7). This is enforced at two independent
   points (local gate in `resolution_runtime.py`, central gate in
   `resolution_governance_gate.py`).
3. **Executable-action threshold is preserved as per-tenant config, not deleted.**
   `action_governance.py` / `TenantActionPolicy` / `policy_type="action_tools"` are
   untouched by this spec (§5). The deleted `_high_value_refund_or_replacement` money-guard
   is restored as `_monetary_commitment_exceeds_threshold`, with its hardcoded `$100`
   constant replaced by tenant-configured `monetary_commitment_threshold_cents` (default
   `0`, i.e. *more* conservative than the old hardcoded `$100` if unconfigured).

## 10. Open items for implementation (Step 2)

- Confirm via `grep` whether any existing test in `tests/test_resolution_runtime.py` or
  `tests/test_resolution_safety_escalation.py` asserts `AUTO_APPROVED`/`SEND_ELIGIBLE` for
  one of the four old hardcoded-safe categories *without* a tenant configuration repository
  — if so, those tests need an in-memory `resolution_autonomy` record fixture added in the
  same task (not a separate cleanup pass).
- `app/tenant/persistence/memory.py`'s `InMemoryTenantConfigurationRepository` (used by
  tests) needs `resolution_autonomy` records seedable the same way `action_tools` records
  are today — confirm the existing seeding helper is generic over `policy_type` (it should
  be, since storage is generic) and extend the test fixtures, not the repository code.
- Add `_validate_resolution_autonomy_policy_payload` to
  `tenant_config_change_request_service.py`, mirroring `_validate_action_policy_payload`
  (§2), calling `validate_resolution_autonomy_policy_parameters`.
