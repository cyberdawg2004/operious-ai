# Operious Pilot Scope

**Status:** Code-grounded audit as of `phase-2-2-stabilized` (2026-06-13).

This document describes only what exists and runs in the codebase today. Every
claim below cites the implementing file and line range. Anything that exists
only as a design spec, roadmap doc, or partial stub is explicitly called out
under **Not Yet Built** and/or **Scope Out** — it is not implied to work.

---

## Scope In

The following end-to-end flow is implemented and exercised by the test suite
(`pytest apps/backend/tests` from repo root: 3113 passed, 422 skipped —
skipped tests require `TEST_DATABASE_URL`/Postgres, which CI provisions):

1. **Inbound ticket arrives** via a tenant webhook (email, WhatsApp, Shulex,
   Lark) or the direct ingress API (Zendesk, WhatsApp, Twilio Voice, work-order
   fulfillment receipts).
2. **Ingress is persisted and dispatched** to the diagnostic pipeline via an
   outbox + Celery.
3. **Diagnostic agent** classifies/analyzes the ticket and retrieves knowledge
   citations.
4. **Resolution proposal** is generated, including a hardcoded category label
   and an LLM-drafted customer reply, grounded against retrieved citations.
5. **Governance gate** evaluates the proposal: citation/grounding coverage,
   safety/legal/fraud keyword screens, monetary-commitment threshold, and a
   tenant-configurable auto-send category allowlist.
6. Depending on the verdict, the proposal is either:
   - **Auto-sent** to the customer via SES (real SigV4-signed API call), or
   - Routed to a **human approval case** (Approval Inbox), or
   - **Escalated** as a safety/legal/fraud governance escalation.
7. Tenant operators can change the auto-send policy (category allowlist,
   monetary threshold) via a dual-control **propose → approve → apply**
   config-change workflow.

---

## Scope Out (Not Implemented / Not Reachable Today)

- **Ticket merging / deduplication.** No `MergeDecision`, `merge_session`,
  `merge_ticket`, or equivalent dedup logic exists anywhere in the codebase
  (confirmed via exhaustive grep across app code, frontend, and git history).
  The only related mechanism is **defect-cluster detection**
  (`apps/backend/app/runtime/defect_cluster_runtime.py:49` —
  `DefectClusterDetectionRuntime`, and `derive_defect_cluster_id` at line 208,
  run by the Celery beat task `scan_for_defect_clusters`), which groups
  *similar defect reports for trend analysis* — it does not merge, link, or
  deduplicate tickets, and produces no merged ticket record.
- **Evidence/attachment persistence beyond citation metadata.** The only
  "evidence" implemented for resolution proposals is a tuple of *knowledge-document
  citation records* (`apps/backend/app/runtime/resolution_runtime.py:895-923`,
  `_normalise_evidence` — `document_id`, `title`, `score`, `chunk_ordinal`,
  etc.). There is no file/image attachment ingestion or persistence model for
  customer-submitted evidence. A separate `app/supervisor/models/evidence.py`
  (`EvaluationEvidence`) exists, but this is part of the **supervisor/execution
  monitoring** subsystem (pointers to tool invocations, governance decisions,
  and state transitions for *internal audit/replay* — see
  `apps/backend/app/supervisor/persistence/records.py:31`), and is unrelated to
  customer-facing evidence or attachments. The untracked spec
  `docs/superpowers/specs/2026-06-12-evidence-attachment-persistence-design.md`
  describes a capability that does **not** correspond to any implemented code —
  it is design-only.
- **Shopify, Jira, Linear channel types.** `TenantChannelType` enumerates
  `SHOPIFY`, `JIRA`, `LINEAR` (`apps/backend/app/tenant/enums.py:8-21`), but
  no webhook adapter or direct-ingress adapter handles these types — they are
  not wired to `_webhook_adapter_for_channel`
  (`apps/backend/app/services/ticket_ingress_service.py:1550-1568`) or
  `_adapter_registry()` (line 1179-1186). Shopify is documented in
  `enums.py:11-14` as "read-only product enrichment" but no consuming code was
  found.

---

## Current Capabilities (Code-Cited)

### 1. Inbound channels

Two distinct ingress paths exist:

**A. Generic tenant webhook endpoint** — `POST /channels/{channel_type}/webhook`
(`apps/backend/app/api/v1/routers/ingress.py:103-150`) →
`TicketIngressService.process_channel_webhook`
(`apps/backend/app/services/ticket_ingress_service.py:432-620`). The channel
type selects the adapter via `_webhook_adapter_for_channel`
(`ticket_ingress_service.py:1550-1568`):

| Channel  | Adapter | Defined at |
|---|---|---|
| `email` (non-SES JSON webhook) | `EmailWebhookAdapter` | `apps/backend/app/boundary/adapters/channel_webhooks.py:66` |
| `whatsapp` | `TenantWhatsAppWebhookAdapter` | `channel_webhooks.py:164` |
| `shulex` | `ShulexWebhookAdapter` | `channel_webhooks.py:315` |
| `lark` | `LarkWebhookAdapter` | `channel_webhooks.py:391` |

Email additionally has an **SES/SNS-specific path**: when the webhook body is
an SNS envelope (`_is_sns_webhook_body`,
`ticket_ingress_service.py:448-458`), `_process_email_sns_webhook`
(`ticket_ingress_service.py:660-`) handles SNS subscription confirmation,
certificate-verified signature checking, and raw-MIME fetch, using
`SesEmailWebhookAdapter` (`apps/backend/app/boundary/adapters/email_ses.py:175`).

All webhook traffic requires a per-tenant HMAC signature
(`_webhook_signature_header_present` / `_webhook_signature_matches_secret`,
`ticket_ingress_service.py:469-503`) and is deduplicated via a
freshness-nonce table (`_webhook_nonce_exists` / `_record_webhook_freshness_nonce`,
lines 520-534) before any tenant DB work occurs. Unknown routes, missing
signatures, and bad signatures all return an identical opaque rejection
(`_uniform_webhook_rejection`, lines 1164-1176) to prevent route/tenant
enumeration.

**B. Direct ingress API** — `POST /ingress`
(`apps/backend/app/api/v1/routers/ingress.py:38-65`) →
`TicketIngressService.process` (`ticket_ingress_service.py:165-`), using
`_adapter_registry()` (`ticket_ingress_service.py:1179-1186`):

| Channel | Adapter |
|---|---|
| Zendesk | `ZendeskWebhookAdapter` |
| WhatsApp | `WhatsAppWebhookAdapter` |
| Twilio Voice | `TwilioVoiceAdapter` |

This path also includes a **semantic circuit breaker** that can quarantine
near-duplicate tickets (`_evaluate_semantic_circuit`,
`ticket_ingress_service.py:184-216`) before they reach the diagnostic pipeline.

Work-order fulfillment receipts have their own ingress path with a dedicated
single-adapter `BoundaryAdapterRegistry`
(`apps/backend/app/services/work_order_fulfillment_receipt_service.py:67`).

### 2. Dispatch

Ingress envelopes are written to an outbox and dispatched to the diagnostic
pipeline via Celery tasks `dispatch_ingress`
(`apps/backend/app/workers/ingress_dispatch_tasks.py:77-100`) and
`reconcile_ingress_dispatch_outbox` (lines 102-`).

### 3. Diagnostic agent

`execute_diagnostic_agent` Celery task
(`apps/backend/app/workers/agent_tasks.py:269-282`, body at
`execute_diagnostic_agent_runtime`, line 317) analyzes/classifies the inbound
ticket and produces a `DiagnosticResult` including `retrieved_citations`
(used as the resolution proposal's evidence — line 982).

### 4. Resolution proposal generation

`_append_resolution_proposal_after_diagnostic`
(`apps/backend/app/workers/agent_tasks.py:1687-1816`) wires together:

- `ResolutionRuntime.create_proposal`
  (`apps/backend/app/runtime/resolution_runtime.py:245-346`) — orchestrates
  category classification, evidence normalization, governance gate
  evaluation, and conversation generation.
- `GroundedConversationGenerationRuntime` (LLM-based reply drafting, citations
  embedded as prompt context —
  `apps/backend/app/runtime/conversation_generation.py:114,256,263-290`).
- `ResolutionOutboundDraftRuntime.create_draft_for_proposal`
  (`agent_tasks.py:1753-1756`, draft logic at
  `apps/backend/app/runtime/resolution_runtime.py:407-527`).

### 5. Grounding / citation coverage

- `_normalise_evidence` (`resolution_runtime.py:895-923`) converts retrieved
  knowledge citations into the proposal's `evidence` tuple
  (rank, document_id, title, document_type/status, score, chunk_ordinal,
  token_count, optional conflict flag).
- `CitationCoverageGroundingChecker.check`
  (`apps/backend/app/runtime/grounding.py:43-80+`) verifies every "claim"
  reply segment cites an approved/current knowledge span; segments tagged
  `question` or `acknowledgment` are exempt from citation requirements
  (`grounding.py:40`), all other/unrecognized segment kinds are treated as
  citable claims (fail-closed, line 39).
- `GroundingPolicy` governance policy
  (`apps/backend/app/runtime/resolution_governance_gate.py:159-225`) wraps the
  checker into the governance chain.
- `ResolutionCommunicationPolicy.evaluate`
  (`resolution_governance_gate.py:80-159`) hard-denies any proposal with
  `evidence_count <= 0` (lines 110-112, reason `"evidence_required"`).

### 6. Hardcoded vs. tenant-configured behavior

**Hardcoded:**
- `_resolution_category()` (`resolution_runtime.py:682-699`) — keyword-based
  classification (e.g. "charging"/"charger"/"battery"/"power" →
  `"charging_issue"`; "warranty"/"replacement"/"replace" →
  `"warranty_replacement_inquiry"`; "refund"/"return"/"chargeback" →
  `"returns_refunds_inquiry"`).
- Safety/legal/fraud/policy-exception keyword screens and the
  "unsupported refund/replacement/warranty promise" pattern check
  (`_evaluate_gate`, `resolution_runtime.py:832-893`).

**Tenant-configured** (via `resolution_autonomy_policy.py`, policy_type
`"resolution_autonomy"`, `RESOLUTION_AUTONOMY_POLICY_TYPE` at line 17):
- `reply_auto_send_categories` (`reply_auto_send.category_allowlist`) — which
  of the hardcoded category outputs are allowed to auto-send
  (`_evaluate_gate`, `resolution_runtime.py:878`:
  `if reasons or category not in autonomy_policy.reply_auto_send_categories`).
- `monetary_commitment_threshold_cents` — dollar amount above which a
  monetary-commitment claim forces human approval regardless of category
  (`_monetary_commitment_exceeds_threshold`, referenced at
  `resolution_runtime.py:854-856`).
- **Fail-closed default:** if no active tenant `resolution_autonomy` policy
  record exists, or it fails to parse, `_empty_policy()`
  (`resolution_autonomy_policy.py:32-36`) returns an empty category allowlist
  and a zero monetary threshold — meaning every proposal requires human
  approval and any monetary commitment is escalated.

### 7. Governed auto-send

- `_request_governed_auto_send` (`apps/backend/app/workers/agent_tasks.py:1869-`)
  is only invoked for proposals whose governance verdict allows it.
- `send_outbound_draft` Celery task (`apps/backend/app/workers/outbound_send_tasks.py:80`)
  and `reconcile_outbound_send_outbox` (line 105) process the send outbox.
- `_ComposedOutboundSendExecutor._send_email_outbox`
  (`outbound_send_tasks.py:383-440`) constructs
  `EmailCustomerReplySendService` and calls `send_draft(...)`.
- `SesV2EmailSender.send_email`
  (`apps/backend/app/boundary/outbound/email_ses.py:94-178`) performs a real
  SigV4-signed HTTPS POST to `https://email.<region>.amazonaws.com/v2/email/outbound-emails`,
  with SSRF-validated, host-allowlisted, IP-pinned transport
  (`validate_public_https_url`, `PinnedIPAsyncHTTPTransport`,
  `follow_redirects=False`), raising `SesV2SendError` on non-2xx.
- The governed reply body (hashed and checksummed in
  `resolution_outbound_drafts`) is wrapped in a professional customer-facing
  template at send time only:
  `apps/backend/app/runtime/customer_email_template.py` —
  `render_customer_email_subject` (line 41), `render_customer_email_body`
  (line 53), `derive_ticket_reference` (line 17) — this wrapping never
  modifies the governed body or its checksum.
- An assertion guards against silent drops: a send-eligible proposal must end
  in an outbox row, approval case, escalation, or logged terminal refusal
  (`agent_tasks.py:1780-1789`).

### 8. Approval / escalation handoff

- `_request_resolution_approval_cases_with_retry` /
  `_request_resolution_approval_cases`
  (`apps/backend/app/workers/agent_tasks.py:1978-2076`) creates human-approval
  cases (Approval Inbox) for proposals requiring approval.
- `_resolution_safety_escalation_governance_decision_id` /
  `_publish_resolution_safety_escalation_if_present` /
  `_publish_resolution_safety_escalation_with_outbox`
  (`agent_tasks.py:2114-2266`) route safety/legal/fraud denials to the
  escalation outbox, consumed by the `create_governance_escalation` Celery
  task (`apps/backend/app/workers/escalation_tasks.py:28-36`).

### 9. Tenant config change workflow (dual control)

`TenantConfigChangeRequestService`
(`apps/backend/app/services/tenant_config_change_request_service.py`) supports
a propose → approve → apply workflow for policy changes, including
`resolution_autonomy` policies (category allowlist, monetary threshold) — this
is the mechanism a tenant operator uses to enable auto-send for specific
categories.

### 10. Defect cluster detection (not ticket merging)

`DefectClusterDetectionRuntime`
(`apps/backend/app/runtime/defect_cluster_runtime.py:49`) and
`derive_defect_cluster_id` (line 208), run via the `scan_for_defect_clusters`
Celery beat task, group similar defect reports for trend/volume analysis. This
is read-only analytics — it does not alter ticket records, merge sessions, or
change resolution flow for individual tickets.

---

## Known Limitations

- **Category taxonomy is hardcoded and narrow.** Only the categories produced
  by `_resolution_category()` (`resolution_runtime.py:682-699`) can ever be
  auto-sent, regardless of tenant policy — a tenant cannot define new
  categories without a code change. (A design spec for a configurable
  taxonomy exists at `docs/superpowers/specs/2026-06-13-resolution-category-taxonomy-design.md`
  but is not implemented.)
- **No ticket merging/deduplication** — near-duplicate or follow-up tickets
  on the same issue are not linked; the only related signal is defect-cluster
  analytics (see Scope Out).
- **No customer-evidence/attachment ingestion** beyond text content and
  knowledge-base citations — customers cannot attach images/files that
  persist with the ticket for agent or reviewer use (see Scope Out).
- **Shopify/Jira/Linear channel types are enum-only** — declared in
  `TenantChannelType` but have no adapter wiring (see Scope Out).
- **Fail-closed by design**: any tenant without an explicit, valid
  `resolution_autonomy` policy gets zero auto-send categories and a zero
  monetary threshold — every proposal requires human approval. This is
  intentional (safety default) but means a pilot tenant must have this policy
  configured via the config-change workflow to demonstrate auto-send at all.
- **422 skipped tests** require `TEST_DATABASE_URL`/Postgres (provisioned in
  CI, `.github/workflows/ci.yml:17-18,45-47,165-166,185-187`) — these cover
  integration paths not exercised by the default local test run.

---

## What a Pilot Can Demonstrate Today

- End-to-end flow for **email (SES)** and **WhatsApp** tickets: inbound
  webhook → dispatch → diagnostic classification → grounded resolution
  proposal → governance evaluation → either (a) auto-sent customer reply via
  real SES, (b) human approval case in the Approval Inbox, or (c) safety/legal
  escalation.
- Tenant-specific auto-send tuning via the dual-control config-change
  workflow: enabling auto-send for one or more of the hardcoded categories
  (e.g. `charging_issue`, `warranty_replacement_inquiry`,
  `returns_refunds_inquiry`) with a configurable monetary-commitment ceiling.
- Grounding/citation enforcement: replies with uncited factual claims, or with
  zero retrieved evidence, are denied or routed to human approval rather than
  sent.
- Defect-cluster trend detection across tickets (analytics view, not a
  ticket-merging UX).

## What a Pilot Cannot Demonstrate Today

- Automatic merging/deduplication of related tickets or threads — does not
  exist.
- Customers attaching photos/files that persist as case evidence — does not
  exist.
- Auto-send for any category outside the hardcoded keyword-based taxonomy in
  `_resolution_category()` — a tenant cannot add a new auto-sendable category
  without a backend code change.
- Ingestion from Shopify, Jira, or Linear — channel types are declared but
  unimplemented.
