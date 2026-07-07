# MCP Connector Integration — Governance Design Spec

**Date:** 2026-07-06  
**Author:** Principal architect review  
**Status:** Design only — no code. Ready for implementation planning.

---

## Preamble: The Invariant

> **Connecting an MCP server cannot create an ungoverned path to money/goods actions.**

This is non-negotiable. The entire design is structured to make it structurally impossible for an external MCP tool — regardless of what the remote server says about itself — to execute a money/goods action without a human approval decision. The invariant is enforced at the same code path (`TenantActionPolicy.evaluate()`, `action_governance.py:320–333`) that enforces it for all other tools. It is not a new mechanism. External MCP tools are adapted to route through the existing gate.

---

## Part 1 — Governance-Wrapping of External MCP Tools

### 1.1 The Commitment Classification Problem

An MCP server exposes N tools. Operious did not author them. Their `name`/`description`/`inputSchema` fields are self-reported by the external server and cannot be trusted as a governance classification. The system must assign a `CommitmentKind` to each tool before it can execute. There are three design options:

**Option A — Tenant declares `commitment_kind` per tool at config time.**  
The tenant sees each tool when connecting the server, assigns `commitment_kind` from the existing enum (`none | record_update | money | goods | service_commitment`), and this declaration is stored in the connector config change-request payload. An MCP tool without a stored classification cannot execute.

**Option B — LLM/heuristic classification from tool schema/description.**  
An automated pass over tool name + description + inputSchema infers `commitment_kind`. Could reduce friction but introduces a classification error path: a tool that sends money could be misclassified as `none`. This is not safe without a human sign-off on the classification.

**Option C — Default everything to `money/goods` (safest) until classified.**  
Unclassified tools are treated as requiring human approval. The tenant can then lower the classification (with governance change-request overhead) when they understand a tool is read-only.

**Recommendation: Option A required, Option C as the runtime default.**

Option A is the right design for tools that will be used in production. The tenant must classify tools explicitly — this is a governance commitment that goes through the `propose/approve/apply` ledger (same as connector config today). This satisfies the "tenant declares commitment_kind per MCP tool" requirement and matches exactly how custom connectors work today via `_CONNECTOR_TYPE_COMMITMENT`.

Option C is the **fail-closed runtime default**: any MCP tool whose classification has not been stored and applied (i.e., is not in the active connector config for that MCP server) is treated as `CommitmentKind.GOODS` + `ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL` at the synthesis layer. This means:
- An unclassified tool: routes to human, never auto-executes.
- A tool classified as `money` or `goods`: routes to human via the inviolable gate, no tenant override.
- A tool classified as `none` or `record_update`: can be auto-approved per tenant policy.

Option B (automated inference) is acceptable as a **UX assist at config time** only — it pre-fills the classification form so the tenant has a starting point, but the tenant must confirm/correct each classification before the change-request can be applied. Automated inference is never the stored classification.

### 1.2 The Canonical Data Model

At config time, the tenant declares MCP tool classifications. The stored representation is an `McpToolDeclaration`:

```
McpToolDeclaration:
  mcp_server_id: str           # the registered MCP server identity
  tool_name: str               # as reported by the MCP server (mcp tool list)
  commitment_kind: CommitmentKind
  description_snapshot: str    # the tool's self-reported description at classify time
  input_schema_snapshot: dict  # the tool's inputSchema at classify time (for audit)
  enabled: bool
```

A collection of `McpToolDeclaration` records forms the tool-manifest for a given MCP server. The manifest is stored in the connector config record for that server (extending the existing `ConnectorConfigRecord` payload, or as a new `MCP_SERVER` change type — see §3 Config Surface).

At **runtime**, for each enabled tool in the manifest, an `OperationDefinition` is synthesized in memory:

```
OperationDefinition:
  connector_id = mcp_server_id
  operation_id = tool_name
  mode = OperationMode.ACT   (for all non-read-only tools)
  commitment_kind = declaration.commitment_kind
  approval_policy = ALWAYS_REQUIRE_APPROVAL  if commitment_kind in {MONEY, GOODS, SERVICE_COMMITMENT}
                    TENANT_POLICY            otherwise
  input_schema = declaration.input_schema_snapshot  (as reference, not enforcement)
  idempotency_strategy = NONE  (MCP transport does not guarantee idempotency)
  target_resource_expr = None  (unknown for generic MCP)
  request_mapping = McpRequestMapping(tool_name=tool_name)  (custom mapping type)
  response_mapping = McpResponseMapping()
```

This `OperationDefinition` is then wrapped in an `McpConnectorTool` (a subtype of `GenericConnectorTool`) and registered in the tool registry. From the governance gate's perspective, it is indistinguishable from any other `GenericConnectorTool` — the gate sees `commitment_kind` and `approval_policy` from the metadata envelope and applies the same decision tree.

### 1.3 The Gate: MCP Tool Calls Through `TenantActionPolicy.evaluate()`

The existing inviolable gate at `action_governance.py:320–333` is the enforcement point. No new gate is needed. The gate fires when `commitment_kind` is in `{MONEY, GOODS, SERVICE_COMMITMENT}` — returning `REQUIRE_APPROVAL` regardless of the tool's declaration or any tenant policy configuration.

The path:

```
Agent requests MCP tool invocation
  → ToolInvoker receives tool_name = "{mcp_server_id}.{mcp_tool_name}"
  → ToolInvoker looks up McpConnectorTool in the tool registry
  → McpConnectorTool.operation_governance_metadata() returns:
      OPERATION_ID_METADATA_KEY          = mcp_tool_name
      COMMITMENT_KIND_METADATA_KEY       = declaration.commitment_kind
      APPROVAL_POLICY_METADATA_KEY       = derived approval policy
  → ToolInvoker calls governance_runtime.evaluate(context)
  → TenantActionPolicy._evaluate_custom_tool(declaration, metadata):
      if commitment_kind in {MONEY, GOODS, SERVICE_COMMITMENT}:
          → REQUIRE_APPROVAL (inviolable, no tenant override)
      if tool not in active manifest:
          → REQUIRE_APPROVAL (unknown = human, fail-closed default)
      else:
          → honor declaration per tenant policy
  → If REQUIRE_APPROVAL: create ActionApprovalRecord, escalate to human queue
  → If ALLOW: McpConnectorTool.invoke() calls MCP server via MCP transport
  → OperationalEvent recorded regardless of decision
```

The key invariant: `McpConnectorTool.invoke()` is **never reached** unless the governance gate returned `ALLOW`. The existing `ToolInvoker` structure already enforces this. An MCP tool classified as `money` or `goods` is structurally identical to a refund tool — it hits the human queue.

**Misdeclaration backstop:** The existing backstop at `action_governance.py:345–358` (which catches tools declared as `none` but carrying `operation_commitment_kind=money` in metadata, or `refund_amount_cents > 0`) provides a second line of defense. For MCP tools, the synthesis layer also checks: if the tool name or description snapshot contains trigger patterns (refund, payment, charge, credit, transfer, send, wire), the synthesized `OperationDefinition` is upgraded to `GOODS`/`ALWAYS_REQUIRE_APPROVAL` regardless of declaration, and the tenant's classification is flagged for re-review. This is a defense-in-depth backstop, not a replacement for explicit classification.

### 1.4 Fail-Closed: MCP Server Unreachable / Error

`McpConnectorTool.invoke()` wraps all MCP transport calls in the same fail-closed pattern `GenericConnectorTool` uses. Concretely:

- `McpServerError`, `McpTransportError`, connection timeout, unexpected response format → `ToolInvocationResult(status="provider_error")` — never a silent success.
- The `ToolInvoker` treats `provider_error` status as a non-terminal result: the governance decision has already been made (ALLOW was granted), so the invocation attempt is logged with `status=failed`, the `ConnectorInvocationRecord` is marked `failed`, and the case returns to human queue for resolution.
- The governance gate is upstream of the MCP call — an MCP server error **cannot bypass the governance gate** because the gate fires before any transport call.
- An MCP server that returns an unexpected success response for a money/goods tool does not matter: the approval was already required and obtained before the call was made.
- If the MCP server is unreachable **at the governance decision phase** (i.e., before `invoke()` — e.g., during a tool manifest refresh), the tool is simply absent from the registry and defaults to unknown → `REQUIRE_APPROVAL`.

### 1.5 Audit: Every MCP Invocation Is a Governed Operational Event

Every MCP tool invocation — regardless of outcome — emits a reconstructable `OperationalEvent` on the existing fabric. Fields populated:

| Field | Value |
|---|---|
| `operational_act` | `OperationalAct.AGENT_TOOL_INVOCATION` (existing) |
| `substrate` | `OperationalSubstrate.AGENTS` |
| `tenant_id` | tenant scope (RLS-enforced) |
| `principal_id` | executing principal or agent identity |
| `governance_decision` | `ALLOW` / `REQUIRE_APPROVAL` / `DENY` |
| `governance_decision_id` | stable ID for replay correlation |
| `metadata.tool_name` | `"{mcp_server_id}.{mcp_tool_name}"` |
| `metadata.mcp_server_id` | the registered server identity |
| `metadata.mcp_tool_name` | as reported by the server at classify time |
| `metadata.commitment_kind` | the stored classification |
| `metadata.mcp_args` | sanitized (credential fields redacted) invocation args |
| `metadata.mcp_response_status` | `ok` / `error` / `timeout` |
| `metadata.approval_id` | the `ActionApprovalRecord` UUID if human-approved |
| `metadata.description_snapshot_hash` | SHA-256 of the tool description at classify time |

The `ConnectorInvocationRecord` (existing idempotency ledger) is extended or complemented with an `McpInvocationRecord` that stores: `mcp_server_id`, `mcp_tool_name`, `args_hash`, `invocation_id` (MCP-level), `response_hash`, `status`, `occurred_at`. This provides exactly-once replay semantics for idempotent tools and a permanent audit trail for non-idempotent ones.

For human-approved actions (money/goods), the approval chain is fully reconstructable: `ActionApprovalRecord → OperationalEvent → McpInvocationRecord → MCP server call`. An auditor can replay exactly what was approved, who approved it, what was sent, and what the server responded.

### 1.6 The Danger Case: MCP Tools That Move Money or Send on the Customer's Behalf

This is the case that must be structural, not policy-dependent.

**Example: Gmail MCP exposes `send_email`. Salesforce MCP exposes `issue_refund`.**

Both of these, if misclassified as `none`, could execute without human approval. The defense layers are:

1. **Structural (inviolable gate):** If declared `money` or `goods`, the gate at `action_governance.py:320–333` fires unconditionally. The tenant cannot configure around it.

2. **Misdeclaration backstop:** If declared `none` but the tool name/description matches money/send/refund heuristics, the synthesis layer upgrades to `goods/ALWAYS_REQUIRE_APPROVAL`. This is checked at manifest synthesis, not just at classify time.

3. **Unknown = human:** A tool not present in the active manifest → `REQUIRE_APPROVAL`. If the MCP server adds new tools between manifest refreshes, those tools are unknown until classified and therefore route to human.

4. **Connector-ledger fail-closed:** The existing `money/goods connector-ledger fail-closed` check (`agent_tasks.py` wiring) means money/goods tools require a `ConnectorInvocationRecord` reservation before the provider call. If that reservation fails, the invocation fails closed — not silently.

5. **No classification bypass path:** The `McpToolDeclaration` payload is part of the connector config change-request. It goes through `propose → approve → apply` (dual-control). A tenant operator cannot unilaterally reclassify a `goods` tool as `none` without a second approver.

**The plain statement of the invariant:**

> An external MCP server connected by a tenant cannot create a path where a money/goods action (sending money, issuing a refund, sending a customer-facing message on behalf of the customer) executes without a human approval decision recorded in the `ActionApprovalRecord` ledger, attached to a specific `OperationalEvent`, with a reconstructable approval chain. This is structural: it holds regardless of what the MCP server says about itself, regardless of what the tenant declares (because the inviolable gate ignores money/goods declarations asking for ALLOW), and regardless of network errors (fail-closed). The only way to execute a money/goods MCP action is to receive a human `APPROVE` decision through the existing case-approval workflow.

---

## Part 2 — OAuth / Credential Model

### 2.1 OAuth Flow (Authorization Code with PKCE)

The tenant connects an external service (e.g., Google Workspace for Gmail MCP, Salesforce) through a standard OAuth 2.0 Authorization Code + PKCE flow. The flow is operator-initiated from the Command Center:

```
1. Tenant operator clicks "Connect [Service]" in Command Center.
2. Backend generates PKCE code_verifier (random 32-byte), code_challenge = S256(code_verifier).
3. Backend stores (tenant_id, mcp_server_id, state_token, code_verifier, expires_at) in a short-lived
   Redis key (TTL = 10 minutes). The state_token is a random 32-byte value, HMAC-bound to tenant_id.
4. Backend returns the OAuth authorization URL (provider's auth endpoint + client_id + redirect_uri
   + scope + code_challenge + state_token) to the Command Center.
5. Command Center redirects the operator's browser to the provider's authorization page.
6. Operator authorizes. Provider redirects to Operious's OAuth callback endpoint:
   /api/v1/mcp/oauth/callback?code={code}&state={state_token}
7. Backend verifies: HMAC-verify state_token → resolve tenant_id, retrieve code_verifier from Redis.
8. Backend exchanges code + code_verifier for access_token + refresh_token via provider's token endpoint
   (server-to-server, not browser-exposed).
9. Backend encrypts {access_token, refresh_token, expires_at, scope, token_type} via OPCRED2
   (see §2.2), stores as a new TenantConfigChangeType.MCP_OAUTH_TOKEN change-request with
   status=PROPOSED.
10. Because the token acquisition happens via operator-initiated OAuth, the operator IS the proposer.
    A second approver (dual-control) must APPROVE the change-request before the token is applied
    (activated). This is the same dual-control ledger used for connector credentials today.
11. On APPLY: encrypted token record moves to status='active' in the
    connector_oauth_tokens table (new, modeled on connector_credentials).
12. Redis state key is deleted after successful use.
```

**Redirect URI pinning:** The OAuth callback URL is server-derived from `PUBLIC_BASE_URL` (same pattern as webhook/voice canonical URLs). The client cannot supply an alternate redirect URI. The provider's registered OAuth app must match exactly.

**Scope minimization:** The tenant specifies required scopes at MCP server registration time. Operious requests only those scopes. The `scope` field is part of the MCP server config change-request payload and goes through dual-control.

### 2.2 Token Storage: OPCRED2 Reuse

OAuth tokens are stored using the same `TenantCredentialEnvelopeEncryptor` + OPCRED2 scheme as connector credentials. The envelope contains:

```
{
  "access_token": "...",
  "refresh_token": "...",    # may be absent for providers that don't issue refresh tokens
  "expires_at": "ISO-8601",  # UTC
  "scope": "...",
  "token_type": "Bearer"
}
```

Stored in a new table `connector_oauth_tokens` (modeled on `connector_credentials`):

```
connector_oauth_tokens:
  tenant_id (PK, FK → tenants, NOT NULL)
  mcp_server_id (PK, varchar)
  token_enc (LargeBinary)              -- OPCRED2 envelope, AAD = f"{tenant_id}:{mcp_server_id}"
  token_hash (varchar 64)              -- SHA-256 of token_enc (for change-request sentinels)
  status: 'pending_validation' | 'active' | 'disabled' | 'expired'
  configured_by (varchar)
  source_approval_id (varchar)
  expires_at (timestamptz)             -- plaintext expiry for refresh scheduler (not the token itself)
  scope (varchar)                      -- plaintext scope list for display
  created_at (timestamptz)
  updated_at (timestamptz)
  FORCE ROW LEVEL SECURITY
```

**Token never returned:** `token_enc` is never included in any API response. The `ConnectorOAuthTokenRepository` follows the same pattern as `ConnectorCredentialRepository` — `get_active()` returns the record for internal use only; response schemas return `credential_hash` + `status` only.

**AAD binding:** The OPCRED2 envelope's AAD is bound to `f"{tenant_id}:{mcp_server_id}"` — the token can only be decrypted in the context of the correct tenant + server pairing. Cross-tenant use is cryptographically impossible.

### 2.3 Token Refresh and Expiry

**Proactive refresh:** A scheduled Celery task (`refresh_mcp_oauth_tokens`) runs on a configurable interval (default: every 15 minutes). It queries `connector_oauth_tokens` where `status='active'` AND `expires_at < NOW() + 10 minutes`. For each expiring token, it:

1. Decrypts the current token envelope.
2. Calls the provider's token endpoint with `grant_type=refresh_token`.
3. Encrypts the new token envelope via OPCRED2.
4. Updates the record (new `token_enc`, new `token_hash`, new `expires_at`).
5. Emits an `OperationalEvent` with act `MCP_OAUTH_TOKEN_REFRESHED`.

**On refresh failure:**
- If `refresh_token` is invalid/revoked: sets `status='disabled'`, emits `MCP_OAUTH_TOKEN_REFRESH_FAILED` event, queues a notification to the tenant operator via the Command Center queue. The MCP server becomes unavailable for new invocations. In-flight human-approved actions that need the token emit `provider_error` and route back to human queue.
- If provider is transiently unavailable: retries with exponential backoff (max 3 attempts). If all retries fail, treats as refresh failure above.
- Refresh failures do **not** silently proceed with an expired token. Expired = `status='expired'`, tool registry returns no tools for that server, all invocations for that server fail-closed.

**Proactive re-authentication:** When `status='disabled'` or `'expired'`, the Command Center surfaces a reconnect prompt. The tenant operator initiates a new OAuth flow. This produces a new change-request that goes through dual-control.

### 2.4 Tenant Isolation

Every OAuth token record is RLS-scoped to `tenant_id`. The same discipline as `connector_credentials`:

- `FORCE ROW LEVEL SECURITY` on `connector_oauth_tokens`.
- `tenant_id NOT NULL` constraint.
- `ConnectorOAuthTokenRepository.get_active(tenant_id, mcp_server_id)` always filters by `tenant_id` and raises `PermissionError` on mismatch.
- The OAuth callback state token is HMAC-bound to `tenant_id` — a callback for tenant A cannot be used to activate a token for tenant B.
- Token refresh task operates per-tenant, per-server record, with row-level lock to prevent concurrent refresh races.

---

## Part 3 — Config Surface

### 3.1 New Change Types

The existing `TenantConfigChangeType` enum gains two new values:

```
MCP_SERVER          # register/update an MCP server's identity + OAuth config + tool manifest
MCP_OAUTH_TOKEN     # store an OAuth token after the authorization dance
```

`MCP_SERVER` payloads are validated by `TenantConfigChangeRequestService.propose()` — the validation checks:
- Server URL is a valid HTTPS URL (SSRF pre-check at propose time; full IP-pin validation at apply time).
- OAuth config is complete (client_id, scopes, auth endpoint, token endpoint).
- Tool manifest is present (at least one tool declared with a `commitment_kind`).
- No tool in the manifest has `commitment_kind` missing.
- For tools with names matching a money/send/refund heuristic: warns if classified below `goods`.

### 3.2 Tenant Operator Flow to Connect an MCP Server

```
Step 1 — Register
  Operator opens Command Center → Connectors → "Add MCP Server"
  Enters: server URL, display name, OAuth provider config (client_id, scopes,
          auth_endpoint, token_endpoint) or API key (non-OAuth path)
  Backend: validates URL (SSRF check), proposes TenantConfigChangeType.MCP_SERVER
           with status=PROPOSED, tool_manifest=[] (empty — tools not yet fetched)
  Change-request is PROPOSED, not yet active.

Step 2 — Authorize (OAuth path)
  Second operator approves the MCP_SERVER change-request (dual-control).
  On APPROVE (not yet APPLY), the Command Center triggers the OAuth flow (§2.1).
  After OAuth completes, an MCP_OAUTH_TOKEN change-request is PROPOSED automatically.
  A third (or the same second) operator approves MCP_OAUTH_TOKEN.
  On APPLY of MCP_OAUTH_TOKEN: token stored as active in connector_oauth_tokens.

Step 3 — Fetch Tools
  After the token is active (or after API key is stored for non-OAuth servers),
  the backend fetches the server's tool list via the MCP protocol (tools/list).
  The fetched tools are presented in the Command Center as a classification table:
    | Tool name       | Description (from server) | Suggested kind (LLM assist) | Your classification | Enabled |
    | send_email      | Send an email via Gmail   | goods (inferred)            | [dropdown]          | [toggle] |
    | read_inbox      | Read email inbox          | none (inferred)             | [dropdown]          | [toggle] |
    | delete_email    | Delete an email           | record_update (inferred)    | [dropdown]          | [toggle] |
  The operator must classify every tool before the manifest can be submitted.
  Any tool left unclassified cannot be submitted (frontend validation).

Step 4 — Classify and Submit
  Operator confirms/overrides all classifications, enables desired tools.
  Command Center submits an updated MCP_SERVER change-request with full tool_manifest.
  This update is PROPOSED (same dual-control flow).
  A second operator APPROVEs. On APPLY:
    - ConnectorConfigRecord for the MCP server is created/updated with the tool manifest.
    - build_tenant_action_tool_registry() will now synthesize McpConnectorTool entries
      for each enabled tool when constructing the agent task runtime.

Step 5 — Enable / Disable Individual Tools
  Any tool enable/disable change is a new MCP_SERVER change-request (delta payload).
  This also goes through propose/approve/apply — operator cannot unilaterally enable
  a tool that was previously approved as disabled.

Step 6 — Reclassify a Tool
  Changing a tool's commitment_kind is a new MCP_SERVER change-request.
  Reclassifying from goods/money to none/record_update requires dual-control.
  The system warns if the new classification is lower than the description-heuristic suggests.
```

### 3.3 Command Center UX for Tool Classification

The classification form:
- Shows the tool's self-reported `name`, `description`, `inputSchema`.
- Shows the LLM-inferred suggested classification (marked "suggested — verify before saving").
- For tools whose description or name contains any of: {send, issue, refund, payment, transfer, charge, credit, wire, delete, remove, update}: pre-fills `goods` and shows a warning banner: "This tool may affect customer commitments. We recommend 'goods' or higher."
- `commitment_kind` is a required dropdown: `read-only (none) | record update | goods | money | service commitment`.
- Each option shows an explanatory tooltip in plain language:
  - `none` — "No side effects visible to the customer. Auto-executes per your action policy."
  - `record_update` — "Updates a record in an external system. Auto-executes per policy."
  - `goods` — "May send something or commit a physical/service action. Always requires a human to approve."
  - `money` — "Moves money or issues a credit. Always requires a human to approve. Cannot be overridden."
- The `Enabled` toggle is separate from classification — a tool can be classified but disabled.
- "Submit for approval" is blocked until all enabled tools have explicit classifications.

### 3.4 Domain-Agnostic Design

The above design has no hardcoded provider names. `mcp_server_id` is a tenant-assigned identifier. The OAuth config (auth endpoint, token endpoint) is tenant-supplied. The tool manifest is fetched from the server. Nothing in the governance layer knows or cares whether the MCP server is Gmail, Salesforce, a custom CRM, or a tenant-built internal service. The governance invariant holds for all of them.

---

## Part 4 — Verification Plan and Honest Estimate

### 4.1 What Can Be Tested With a Mock MCP Server

The following can be covered without external OAuth accounts:

**Governance invariants (fully mockable):**

- `McpConnectorTool.invoke()` is never called when governance returns `REQUIRE_APPROVAL` or `DENY`. Spy on the tool's `invoke()` method; assert zero calls when `commitment_kind=goods`.
- Unclassified tool (absent from manifest) → `REQUIRE_APPROVAL`. Construct a tool registry with no manifest entry for a given tool name; assert gate decision.
- Misdeclaration backstop: tool declared `none` with `description_snapshot` containing "refund" → upgraded to `goods` at synthesis. Unit test on `_synthesize_operation_definition()`.
- Inviolable gate: tool declared `money`, policy declares `decision=allow` → still `REQUIRE_APPROVAL`. Same pattern as existing `test_custom_connector_money_governance_gate.py` Claim 2.
- Fail-closed on MCP server error: mock transport raises `McpTransportError` → `ToolInvocationResult(status="provider_error")` → case routes to human queue.
- Fail-closed on unexpected response format: mock transport returns malformed response → `provider_error`.
- `OperationalEvent` is emitted with correct `governance_decision` regardless of outcome.
- `McpInvocationRecord` is created with correct fields for successful and failed invocations.
- Tool manifest refresh: new tools added by server between refreshes are unknown → `REQUIRE_APPROVAL`.
- Token expiry: `status='expired'` token → no tools synthesized → all invocations fail-closed.

**OAuth/credential model (partially mockable):**

- State token HMAC verification: wrong tenant_id → callback rejected.
- State token TTL: expired state → callback rejected.
- OPCRED2 token storage: encrypt/decrypt round-trip with correct AAD binding.
- Cross-tenant isolation: token for tenant A cannot be retrieved under tenant B session.
- RLS: `connector_oauth_tokens` FORCE RLS coverage (same invariant test pattern as `test_connector_rls.py`).
- Token refresh failure path: mock refresh endpoint returns `invalid_grant` → `status='disabled'` + event.
- Concurrent refresh race guard: two tasks racing to refresh the same token → only one succeeds.

**Config surface (mockable):**

- `MCP_SERVER` change-request with missing tool classifications → `propose()` validation fails.
- `MCP_SERVER` change-request with a tool classified `none` whose name contains "send" → warning event.
- Dual-control: proposer cannot be approver (existing test pattern).
- `apply()` for `MCP_SERVER`: tool manifest is persisted in `ConnectorConfigRecord`.
- `build_tenant_action_tool_registry()` with a mock `ConnectorConfigRecord` containing MCP tools: correct `McpConnectorTool` instances are synthesized with correct `commitment_kind`.
- Tool enable/disable: disabled tool is absent from registry; enabled tool is present.

### 4.2 What Requires Real External OAuth Accounts

The following cannot be meaningfully tested without real provider credentials:

- Full OAuth authorization code + PKCE dance: requires a real browser redirect to Google/Salesforce/etc., real authorization UI, and a real `code` in the callback.
- Token exchange and refresh: requires real provider token endpoints.
- `tools/list` over a real MCP server: requires a real server with real credentials.
- MCP tool invocation producing a real side effect (e.g., Gmail `send_email` actually sends): requires real credentials, explicit test account, and an approval workflow. This is the live provider drill equivalent of the existing connector live tests.
- Token expiry in real time: requires waiting for real token TTL (or using provider sandbox short-TTL tokens).

**The honest statement:** Full end-to-end verification (including the OAuth dance, real token storage + refresh, and a real MCP tool invocation through the governance gate) requires:
- A Google Workspace test account with Gmail API OAuth app configured.
- OR a Salesforce sandbox with a connected app configured.
- OR a self-hosted MCP server with a test OAuth provider (most practical for CI).

The self-hosted MCP server + local OAuth mock (e.g., `oauth-mock-server`) path is the recommended CI approach. Real Google/Salesforce accounts are needed for final production-readiness verification (equivalent to the existing S-10 live proof requirement).

### 4.3 Honest Effort and Risk Estimate

**Summary: 6–9 weeks of focused engineering. The riskiest part is the MCP protocol integration and OAuth callback security, not the governance layer.**

**Breakdown:**

| Component | Effort | Risk |
|---|---|---|
| `McpConnectorTool` + `McpInvocationRecord` | 1.5 weeks | Low — extends existing pattern |
| Tool registry synthesis (manifest → OperationDefinition) | 0.5 weeks | Low — existing `_connector_tool_from_config()` pattern |
| `connector_oauth_tokens` table + repository + OPCRED2 | 1 week | Low — extends existing `connector_credentials` |
| OAuth flow (backend: state, callback, exchange, store) | 1.5 weeks | Medium — OAuth edge cases (state replay, CSRF, PKCE verification) |
| Token refresh Celery task | 0.5 weeks | Low |
| `MCP_SERVER` + `MCP_OAUTH_TOKEN` change-request types | 1 week | Low — extends existing ledger |
| Command Center classification UI | 1.5 weeks | Medium — UX complexity for tool manifest |
| MCP transport layer (client, server discovery, tools/list, tools/call) | 1 week | Medium — MCP spec compliance, error handling |
| Tests (governance invariant suite, mock MCP server) | 1 week | Low |
| Live provider drill + S-10 equivalent evidence | not included | High — external dependency |

**The riskiest part is not the governance layer.** The governance layer is the most well-specified and best-tested part of the codebase. Routing an MCP tool through it is a clean extension. The risk is:

1. **OAuth callback security.** The OAuth dance introduces a browser redirect path. If the state token is not properly HMAC-bound and the redirect URI is not exactly pinned, this becomes an open redirect / CSRF vector. The SSRF protection on the token exchange endpoint (server-to-server call to provider's token endpoint) must also be applied — the provider's token endpoint URL is tenant-supplied and must be validated. This is the highest-risk implementation detail.

2. **MCP protocol compliance.** The MCP specification is evolving. Tool schemas, `tools/call` error formats, and authentication modes vary across servers. The adapter layer must be defensive about what the server returns — unexpected formats must fail closed, not silently interpret as success.

3. **Misdeclaration risk at classify time.** If a tenant classifies a money/send tool as `none`, the misdeclaration backstop provides defense-in-depth but is heuristic. A sufficiently obscure tool name ("process_adjustment") could slip through. The defense here is the process: dual-control change-requests mean two humans must agree on the classification, which materially reduces the risk of accidental misdeclaration.

4. **Governance moat threat from careless implementation.** The single highest-risk failure mode for this feature is an implementation that adds a "fast path" for MCP tools that bypasses `ToolInvoker` — e.g., calling the MCP server directly from an agent without routing through the governance gate. This must be architecturally prevented: `McpConnectorTool.invoke()` must only be reachable through `ToolInvoker`, and `ToolInvoker` must only be constructed with a governance runtime. This is the existing discipline; it must extend to the MCP path without shortcuts.

**What "2 weeks" would buy:** A local-only prototype with a mock MCP server, governance gate integration, and OPCRED2 token storage. No real OAuth, no production-ready Command Center UI, no live provider proof.

**What "6–9 weeks" buys:** A production-ready implementation with real OAuth, dual-control change-request ledger integration, Command Center classification UI, OPCRED2-backed token storage + refresh, governance gate integration with full invariant test suite, and a mock-MCP CI suite. Still requires a separate live-provider drill sprint (equivalent to the existing Stage 3 live external call work).

**What could go wrong and threaten the governance moat:**

- A fast-path implementation that calls the MCP server outside `ToolInvoker` — immediately breaks the invariant.
- OAuth state token not HMAC-bound — enables cross-tenant token injection.
- Tool manifest fetched at runtime (not at classify time) and used to bypass classification — removes the human-classification step.
- `commitment_kind=None` synthesis fallback that defaults to `none` instead of `goods` — unclassified tools would auto-execute.
- Token refresh updating the record without re-running OPCRED2 encryption — leaks plaintext in the event of a DB compromise.

All of these are avoidable with the design above and the existing test patterns. The governance moat is safe if the implementation follows the seams.

---

## Appendix: Seam Reference

The following existing code paths are directly extended (not replaced) by this design:

| Seam | File | Role in MCP integration |
|---|---|---|
| `TenantActionPolicy.evaluate()` inviolable gate | `app/agents/tools/action_governance.py:320–333` | Unchanged — money/goods MCP tools hit this gate |
| `_evaluate_custom_tool()` unknown-tool default | `app/agents/tools/action_governance.py` | Unchanged — unclassified MCP tools route to REQUIRE_APPROVAL |
| `GenericConnectorTool` | `app/agents/tools/connectors/generic.py` | `McpConnectorTool` subclasses or mirrors this |
| `operation_governance_metadata()` | `app/agents/tools/connectors/generic.py:181` | `McpConnectorTool` implements same method |
| `build_tenant_action_tool_registry()` | `app/agents/tools/actions/__init__.py:77` | Extended to synthesize McpConnectorTool from MCP manifest |
| `_CONNECTOR_TYPE_COMMITMENT` map | `app/agents/tools/actions/__init__.py:57` | Pattern reused for fail-closed commitment kind defaults |
| `ConnectorCredentialRepository` + `ConnectorScopedCredentialRuntime` | `app/agents/tools/connectors/credentials.py` | `ConnectorOAuthTokenRepository` mirrors this |
| `TenantCredentialEnvelopeEncryptor` (OPCRED2) | `app/tenant/credentials.py` | Reused verbatim for OAuth token encryption |
| `TenantConfigChangeRequestService.propose/approve/apply()` | `app/services/tenant_config_change_request_service.py` | Extended with `MCP_SERVER` + `MCP_OAUTH_TOKEN` change types |
| `TenantConfigChangeType` enum | `app/tenant/change_requests.py:23` | Two new values: `MCP_SERVER`, `MCP_OAUTH_TOKEN` |
| `OperationalEvent` | `app/events/event.py:44` | Unchanged — new `operational_act` values added to enum |
| `ConnectorInvocationRecord` (idempotency ledger) | `app/agents/tools/connectors/` | `McpInvocationRecord` follows same pattern |
| `_action_orchestration_runtime()` | `app/workers/agent_tasks.py:2903` | `McpConnectorTool` entries appear in the registry; no other change |
