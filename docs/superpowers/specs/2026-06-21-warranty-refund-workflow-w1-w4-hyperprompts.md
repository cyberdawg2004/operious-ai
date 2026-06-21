# Warranty/Refund Auto-Resolution Workflow — W1–W4 Hyperprompts

Companion to the approved Step-0 scoping spec (capability breakdown, reuse
survey, eligibility-core design, recommended sequence). W0 (Templates KB) is
done and merged. This file is the literal, pasteable build prompt for each
remaining phase — same ROLE/BUILD/CONSTRAINTS/DELIVERABLE structure used for
every prior phase in this codebase, so each phase can be handed off, reviewed,
or resumed cold with zero re-derivation.

**Operating assumption, fixed across all four phases unless a future prompt
explicitly revises it**: the workflow always produces a recommendation for a
human to approve or reject. There is no confidence threshold, tenant trust
tier, or dollar amount at which it auto-executes a money/goods action. If a
future phase wants to relax this, that is a new, explicit decision — not a
default this roadmap leaves open.

Three decisions from the Step-0 spec are resolved below (with rationale) so
these prompts are buildable as written. One — W4's auto-send vs
draft-for-review — is deliberately left OPEN; W4's prompt starts by forcing
that call before any code, per the original spec's flag.

---

## W1 — Eligibility-Verification Core

```
ROLE: Senior engineer on Operious. W1 of the warranty/refund workflow: the
ELIGIBILITY-VERIFICATION CORE. This is the governance-sensitive heart of the
whole workflow — it takes B3's extracted invoice fields and a tenant's
warranty/refund rules and produces a grounded, fail-closed eligibility
determination. This PR produces DATA ONLY: no approval-queue wiring (W2), no
remedy/inventory selection (W3), no customer-facing dispatch (W4), and no
execution of any kind.

DECISION ALREADY MADE (build to this, don't re-open it): ONE new tenant
policy type, not several. Call it "warranty_refund_rules". It bundles
warranty_window_days, authorized_resellers, required_evidence_by_claim_type,
and remedy_sequence_by_claim_type in one versioned, dual-control-approved
TenantGovernancePolicyRecord — mirroring resolution_taxonomy's existing
shape (one policy, several related concerns), not resolution_autonomy's
narrower one (single concern). This keeps the tenant-config surface small:
one policy to version, approve, and audit per tenant, not four.

REUSE (cite, don't reinvent):
- TenantGovernancePolicyRecord + the policy_type/parameters/version/
  approved_by/source_approval_id shape (app/tenant/persistence/records.py) —
  resolution_taxonomy_policy.py and resolution_autonomy_policy.py are your
  two precedents for how a new policy type defines its own parser/validator
  and gets wired into _validate_payload in
  tenant_config_change_request_service.py (the SAME dual-control
  propose/approve/apply flow you just wired templates into for W0 — reuse it
  again here, don't build a second config path).
- ExtractedOrderFields / ExtractedField (app/cognition/extraction.py) — the
  ONLY input from B3. value=None / confidence=None / source="none" is the
  ONLY absence state; never treat a missing field as anything but missing.
- _evaluate_gate's existing fail-closed shape in
  app/runtime/resolution_runtime.py (_extraction_completeness_reasons,
  _REQUIRED_EXTRACTION_FIELDS_BY_ACTION_TYPE) — this is the PATTERN to
  generalize (a hardcoded dict checking required fields per action type),
  not infrastructure to call directly. W1's required-evidence check is the
  same idea, driven by the new policy's required_evidence_by_claim_type
  instead of a hardcoded dict.

BUILD:
1. warranty_refund_rules policy type: parser/validator module mirroring
   resolution_taxonomy_policy.py's structure (a frozen dataclass policy
   shape, a ParseError class, a resolve_* function reading the active
   TenantGovernancePolicyRecord). Wire into _validate_payload for the
   POLICY change type (same as resolution_taxonomy/resolution_autonomy
   already are).
2. EligibilityDetermination dataclass: verdict (one of "eligible",
   "ineligible", "cannot_determine" — exactly these three, no others),
   claim_type, grounding (tuple of per-check records, each citing the
   field name, its value/confidence/source, the rule applied, and the
   check's individual result), missing_evidence (tuple of field names),
   conflicting_evidence (tuple of field names flagged ambiguous).
3. The determination function itself: pure (no DB, no I/O — takes
   ExtractedOrderFields + the resolved policy + claim_type, returns
   EligibilityDetermination). Order of operations, in this exact order:
   a. Look up required_evidence_by_claim_type[claim_type]. Unknown claim
      type -> cannot_determine, zero rule evaluation.
   b. For every required field: value is None, OR confidence == "low" ->
      add to missing_evidence. ANY entry in missing_evidence -> verdict is
      cannot_determine, STOP — no rule evaluation runs on incomplete
      evidence, ever.
   c. Only with complete, sufficient-confidence evidence: evaluate each
      rule (warranty window, authorized reseller, etc.), each producing one
      grounding record citing the literal field value used.
   d. If you need to detect "conflicting evidence" beyond what B3 already
      encodes via confidence="low" on ambiguous extraction (B3's
      adversarial-ambiguity break-control already fails closed at the
      extraction layer) — do not re-implement ambiguity detection here;
      trust B3's confidence signal. A field B3 marked low-confidence due to
      conflicting source text already lands in missing_evidence via (b).

BREAK-CONTROLS:
- Missing required field (value=None) -> cannot_determine, grounding is
  empty, missing_evidence lists exactly that field. No rule runs.
- Low-confidence required field (confidence="low", value present) ->
  cannot_determine — confidence floor applies even though a value exists.
- All required evidence present + high/medium confidence, rules favor
  eligible -> verdict eligible, every grounding record cites the literal
  evidence value and the rule.
- All required evidence present, a rule fails (e.g. outside warranty
  window) -> verdict ineligible, grounding cites why.
- Unknown claim_type (no entry in required_evidence_by_claim_type) ->
  cannot_determine, not a crash, not a silent default-eligible.
- Two tenants with DIFFERENT warranty_window_days / remedy_sequence on the
  SAME extracted fields produce DIFFERENT determinations — proves nothing
  is hardcoded.
- Policy change request requiring template_purpose-style required-field
  validation in _validate_payload (mirroring W0's pattern) for
  warranty_refund_rules creation.

CONSTRAINTS: pure data out — no ApprovalQueueIngressService call (W2), no
connector/inventory call (W3), no outbound send (W4). Domain-agnostic: no
hardcoded warranty days, reseller names, or claim types anywhere — every
example in your tests is clearly a TEST fixture, not a default. tsc/pyright/
ruff clean, FULL CI green on origin, git status clean. NOT done until
committed + pushed to origin + CI green + clean.

DELIVERABLE: warranty_refund_rules policy type (parser + dual-control
wiring), EligibilityDetermination + the pure determination function,
break-control tests proving fail-closed on missing/low-confidence/unknown-
claim-type, tenant-configurability proof, and committed/pushed-to-origin/
CI-green/clean confirmation.
```

---

## W2 — Wire Eligibility Core → Approval Queue

```
ROLE: Senior engineer on Operious. W2 of the warranty/refund workflow:
smallest possible PR. Take W1's EligibilityDetermination and submit it to
the EXISTING human-approval queue. No new approval infrastructure — this PR
is pure wiring.

REUSE (cite, don't reinvent):
- CaseApprovalEntryCategory.REFUND_WARRANTY (app/approvals/enums.py) —
  already exists, currently unused by any producer. This PR is its first
  real producer.
- ApprovalQueueIngressService.request_case_review (app/approvals/ingress.py)
  — the producer-side API. CaseApprovalReviewRequest's
  recommended_action: Mapping[str, Any] | None and issue_summary fields are
  where W1's determination goes — confirm the exact shape against the
  current CaseApprovalReviewRequest dataclass before building (it may have
  evolved since the Step-0 survey).
- The dedup_key derivation already inside request_case_review (tenant +
  execution + dispatch + session + entry_category) — do not build a second
  idempotency mechanism; confirm it's sufficient for a re-run of the same
  ticket and rely on it.

BUILD:
1. A trigger function: given a ticket's diagnostic output (claim_type +
   B3 extracted fields + tenant_id + the existing
   execution_id/dispatch_id/session_id triple), runs W1's determination,
   then calls request_case_review with entry_category=REFUND_WARRANTY,
   recommended_action carrying {claim_type, verdict, grounding,
   missing_evidence} verbatim, issue_summary as a short human-readable
   line (not a fabricated summary — derive it directly from the
   determination, e.g. "Warranty claim: {verdict}, evidence:
   {missing_evidence or 'complete'}").
2. Decide and document the hook point: where in the existing
   diagnostic/resolution pipeline does this trigger fire? (Candidates:
   alongside the existing _evaluate_gate call in resolution_runtime.py
   when category matches a configured warranty/refund claim type, or a
   dedicated new step gated on the tenant having a warranty_refund_rules
   policy configured at all.) This is an architectural call this prompt
   does not make for you — investigate the current resolution_runtime.py
   flow first and pick the point that doesn't duplicate or race the
   existing _evaluate_gate / CaseApprovalEntryCategory.
   RESOLUTION_REQUIRE_APPROVAL path it already has.

BREAK-CONTROLS:
- An eligible determination creates a REFUND_WARRANTY case with full
  grounding attached and visible.
- An ineligible determination ALSO creates a case (a human still reviews a
  denial recommendation — this workflow never auto-denies either).
- A cannot_determine determination creates a case flagged distinctly (so a
  human sees "needs more evidence" rather than a verdict) — or, if W4 isn't
  built yet, this is where a cannot_determine ticket currently lands
  (manual escalation) until W4 exists to probe automatically.
- Re-running the same ticket (same execution_id/dispatch_id/session_id)
  does not create a duplicate case — proves the existing dedup_key is
  sufficient.
- Tenant isolation: tenant A's case never visible under tenant B's query.

CONSTRAINTS: no remedy/inventory selection (W3 — recommended_action carries
the verdict only, not yet a specific remedy), no probe dispatch (W4), no
execution. tsc/pyright/ruff clean, FULL CI green on origin, git status
clean. NOT done until committed + pushed to origin + CI green + clean.

DELIVERABLE: the trigger function, the documented hook-point decision (with
citation to exactly where in resolution_runtime.py or elsewhere it fires),
break-control tests, and committed/pushed-to-origin/CI-green/clean
confirmation.
```

---

## W3 — Remedy Ladder + Inventory Check

```
ROLE: Senior engineer on Operious. W3 of the warranty/refund workflow: turn
an "eligible" determination into a SPECIFIC, availability-checked remedy
recommendation (replacement → refurbished → refund, tenant-ordered) before
it reaches the human.

DECISION ALREADY MADE (build to this, don't re-open it): the inventory/
availability check runs BEFORE the case reaches the approval queue, not at
execution time. Rationale: the human approver should see "replacement
unavailable, refurbished recommended instead" rather than approve a remedy
that then fails at dispatch — a worse experience and a wasted approval
cycle. This means W3's output REPLACES W2's bare verdict in
recommended_action with a specific, availability-confirmed remedy before
W2's request_case_review call fires; sequence W3's logic to run between W1
and W2's existing trigger function, not after it.

REUSE (cite, don't reinvent):
- ResolutionTaxonomyPolicy.actions_for / ResolutionTaxonomyCategory
  (app/runtime/resolution_taxonomy_policy.py) — recommended_actions is
  already an ORDERED tuple; W1's remedy_sequence_by_claim_type is the
  warranty/refund-specific analog. Don't invent a second "ladder" concept;
  if a category-level recommended_actions ordering can express this
  directly, prefer wiring into that over a parallel structure.
- ConnectorTool base (app/agents/tools/connectors/base.py) + refund.py/
  replacement.py/warranty.py — a fourth connector instance for inventory
  check is the same generic-REST-per-tenant pattern, nothing new at the
  abstraction level.
- ShopifyAPIClient.get_product_by_sku (app/boundary/shopify/client.py) —
  for tenants whose OMS is Shopify, this already returns
  inventory_quantity; check whether your tenant's OMS channel type is
  Shopify before reaching for a new generic connector — reuse this read
  path when it applies instead of standing up a redundant one.

BUILD:
1. For an "eligible" determination: walk the tenant's
   remedy_sequence_by_claim_type[claim_type] in order. For each remedy
   step, check availability (Shopify read path or a new generic inventory
   connector, tenant-configured which). First AVAILABLE remedy wins;
   attach it (plus which steps were tried and why skipped) to the
   determination payload that flows into W2.
2. Fail-soft on the inventory check itself: a connector error/timeout
   checking one remedy step's availability does not crash the workflow or
   silently skip to the next step pretending it checked — it must be
   recorded as "availability_unknown" for that step, and the human sees
   that explicitly rather than a confident wrong answer.
3. An "ineligible" or "cannot_determine" determination skips this step
   entirely — no inventory check runs for a remedy that was never going to
   be offered.

BREAK-CONTROLS:
- Replacement unavailable, refurbished available -> recommendation is
  refurbished, with a record showing replacement was checked and rejected
  for availability, not silently dropped.
- All remedy steps unavailable -> recommendation flags "no remedy
  currently available" distinctly from "ineligible" — these must never be
  conflated; a human needs to know the customer IS entitled to something,
  it just isn't in stock right now.
- Inventory connector failure (simulate a timeout/error) -> that step is
  marked availability_unknown, not silently treated as available OR
  unavailable, and the workflow still produces a recommendation (degrades,
  never crashes the whole determination).
- Two tenants with different remedy_sequence_by_claim_type orderings on
  the identical eligible determination produce different recommended
  remedies — proves the ladder is tenant-configured, not domain-default.

CONSTRAINTS: still no execution and no probe dispatch (W4) — this PR only
enriches the recommendation that reaches the SAME human-approval queue from
W2. tsc/pyright/ruff clean, FULL CI green on origin, git status clean. NOT
done until committed + pushed to origin + CI green + clean.

DELIVERABLE: the availability-gated remedy selection, the
fail-soft-on-connector-error handling, break-control tests for the ladder
fallthrough + tenant-configurability + fail-soft, and committed/pushed-to-
origin/CI-green/clean confirmation.
```

---

## W4 — Probe Dispatch for Missing Evidence

```
ROLE: Senior engineer on Operious. W4 of the warranty/refund workflow: when
W1's determination is cannot_determine because evidence is missing, use
W0's Templates KB to ask the customer for it.

STOP AND CONFIRM BEFORE WRITING ANY CODE — this is the one decision the
Step-0 spec deliberately left open and this roadmap does not resolve for
you: does the probe message AUTO-SEND, or does it draft-for-human-review
like every money/goods recommendation in this workflow? A customer-facing
message asking for evidence is itself outbound communication with its own
governance footprint — it is not nothing just because it isn't money. Get
an explicit answer before building either path; do not default to
auto-send because it's simpler, and do not default to draft-for-review
just because it's "safer" without asking — both have real product cost
(auto-send risk vs. response-latency cost) and this is Imad's call.

REUSE (cite, don't reinvent):
- TenantConfigurationRuntime.get_approved_template (app/tenant/runtime.py,
  built in W0) — the (tenant, purpose, channel) lookup. Returns None on no
  match; that is not an error, see break-controls below.
- extract_placeholders (app/tenant/template_placeholders.py, built in W0)
  — use it to validate BEFORE sending, not just to discover placeholders.
- ResolutionAutonomyPolicy.reply_auto_send_categories
  (app/runtime/resolution_autonomy_policy.py) — IF the answer to the
  auto-send question above is "follow the existing autonomy pattern," this
  is the existing mechanism to extend, not a new one to invent.
- Whatever the existing per-channel outbound send path already is for a
  resolution reply (the WhatsApp/email customer-reply send service this
  codebase already has for resolution drafts) — a probe message is just
  another outbound reply; do not build a second send pathway.

BUILD (shape depends on the auto-send decision above, but regardless):
1. Missing-field -> template purpose mapping: tenant-configured (e.g. via
   the SAME warranty_refund_rules policy from W1, or a sibling mapping) —
   "purchase_date missing" -> "probe.missing_invoice", NOT a hardcoded
   if/elif chain. Confirm where this mapping lives before building it as a
   throwaway.
2. Substitution: given a template's content and the determination's
   context (claim_type, ticket fields, missing_evidence), fill every
   placeholder extract_placeholders finds. ANY placeholder that cannot be
   filled from available context is a hard stop for that send — never
   send text with a literal unfilled {placeholder} token.
3. Dispatch (or draft) via the existing channel-appropriate send path,
   gated however the auto-send decision resolved.

BREAK-CONTROLS:
- No approved template exists for the (tenant, purpose, channel) the
  missing field maps to -> the ticket still escalates to a human (W2's
  existing cannot_determine case) — absence of a template degrades to
  "human handles it," never a crash, never a fabricated message.
- A template exists but references a placeholder the determination cannot
  fill -> the send is blocked, not sent malformed; this must surface as
  loudly as the missing-template case, not silently.
- A template exists, all placeholders fillable -> the exact expected
  substituted text is produced (or drafted, per the auto-send decision),
  verified character-for-character against a fixture.
- Whichever auto-send/draft path was chosen, the OTHER path is proven NOT
  to fire — if draft-for-review was chosen, no outbound send call happens
  anywhere in this flow without the human step.

CONSTRAINTS: domain-agnostic — no hardcoded probe wording or purpose names
outside test fixtures. tsc/pyright/ruff clean, FULL CI green on origin, git
status clean. NOT done until committed + pushed to origin + CI green +
clean.

DELIVERABLE: the confirmed auto-send/draft-for-review decision (recorded,
not assumed), the missing-field-to-purpose mapping + its tenant-config
home, substitution with hard-stop-on-unfillable-placeholder, break-control
tests for missing-template / unfillable-placeholder / successful dispatch,
and committed/pushed-to-origin/CI-green/clean confirmation.
```
