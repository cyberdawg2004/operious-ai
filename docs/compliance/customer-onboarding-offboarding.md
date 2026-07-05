# Customer Onboarding and Offboarding Procedures

> **Scope:** Operious AI platform — tenant lifecycle management.
> **Audience:** Platform administrators, tenant operators, compliance officers.
> **Last updated:** 2026-07-05

All API paths below are relative to the configured `API_V1_PREFIX` (default
`/api/v1`).  Capability requirements are the minimum required in the
`AuthorityContext` resolved by the request.

---

## 1. Onboarding

### Step 1 — Platform admin creates tenant record

**Endpoint:** `POST /api/v1/tenant/lifecycle/tenants`
**Required capability:** `platform.tenant.admin` (resolved via `require_platform_lifecycle_admin`)
**Body:**

```json
{
  "tenant_id": "acme-corp"
}
```

**Expected response:** `201 Created` with a `TenantLifecycleResponse` containing
the new tenant's `tenant_id`, `status: "provisioning"`, and `created_at`.

This call inserts a row into the `tenants` table and initialises the tenant in
`provisioning` status.  RLS is active from this point: rows can only be written
or read under the `acme-corp` tenant context.

---

### Step 2 — Platform admin provisions tenant config admin

**Endpoint:** `POST /api/v1/tenant/lifecycle/tenants/admin`
**Required capability:** `platform.tenant.admin`

Grants the designated principal `tenant.config.admin` authority within the
new tenant's scope.  Without this step the tenant operator cannot create
channels, propose policies, or manage connector configs.

---

### Step 3 — Operator creates channel configuration

**Endpoint:** `POST /api/v1/tenant/channels`
**Required capability:** `tenant.channel.direct_apply` (via `require_tenant_channel_direct_apply`)
**Body:**

```json
{
  "channel_type": "email",
  "routing_address": "support@acme-corp.com",
  "credentials": { "mode": "managed", "region": "us-east-1" },
  "webhook_secret": "<generated-secret>",
  "status": "pending_validation"
}
```

WhatsApp and other self-service channels have dedicated endpoints:

- `POST /api/v1/tenant/whatsapp/self-service` — WhatsApp Business embedded signup
- `POST /api/v1/tenant/email/self-service` — SES self-service setup

Channel updates go through `PUT /api/v1/tenant/channels/{config_id}`.

---

### Step 4 — Operator uploads knowledge documents

**Endpoint:** `POST /api/v1/knowledge/documents`
**Required capability:** `tenant.knowledge.write`

Documents enter quarantine on upload (`review_status: "quarantined"`).  The
platform will not surface them to the resolution runtime until they are approved.

**Approval workflow:**

1. A second operator or platform admin calls
   `POST /api/v1/approvals/cases/{approval_id}/approve`.
2. On approval `review_status` transitions to `"approved"` and vector indexing
   is queued.
3. If rejected, `review_status` becomes `"rejected"` and the document remains
   inert.

---

### Step 5 — Operator configures resolution autonomy policy

All governance policy changes (resolution autonomy, action tools,
warranty/refund rules, resolution taxonomy) go through the dual-control
change-request ledger — direct writes are rejected by the backend.

**Propose a policy change:**

```
POST /api/v1/tenant/config-change-requests
```

**Approve (different principal required):**

```
POST /api/v1/tenant/config-change-requests/{change_request_id}/approve
```

**Apply (after approval):**

```
POST /api/v1/tenant/config-change-requests/{change_request_id}/apply
```

The `approved_by` principal must differ from `proposed_by` (enforced by the
`approver_distinct` check constraint on `tenant_config_change_requests`).

---

### Step 6 — Operator configures connector configs for action tools

Connector configurations (OMS, ERP, CRM integrations) follow the same
dual-control flow via `change_type: "connector"` change requests.

Credential rotation is handled separately:

```
POST /api/v1/tenant/connector-configs/credentials/propose
```

This creates a `credential_update` change request that must be approved by a
different principal before the new credentials are active.

---

### Step 7 — Verify: webhook health check and smoke probe

**Verify channel:**

```
POST /api/v1/tenant/channels/{config_id}/verify
```

Returns validation evidence including webhook reachability.

**Connector test:**

```
POST /api/v1/tenant/connector-configs/test
```

Fires a synthetic call against the configured endpoint and returns the HTTP
status and latency.

**Smoke probe:** Submit a synthetic ticket through the boundary ingress and
confirm the session reaches a terminal lifecycle phase (`closed` or `resolved`)
with a governance `ALLOW` decision on record.

---

## 2. Offboarding

### Step 1 — Pause all channels

Prevents new tickets from entering the system while audit data is being
prepared.

```
PUT /api/v1/tenant/channels/{config_id}
Body: { "status": "disabled" }
```

Repeat for every `TenantChannelConfiguration` returned by
`GET /api/v1/tenant/channels`.

---

### Step 2 — Export audit data

```
GET /api/v1/audit/export
```

Returns a time-windowed export of governance decisions, boundary events,
session records, and QA scores.  Store the response body offline before
proceeding.  The export is signed — use `POST /api/v1/audit/verify` to
confirm integrity post-download.

---

### Step 3 — Submit DSAR erasure request

```
POST /api/v1/data-protection/erasure-requests
Body: {
  "subject_type": "tenant",
  "subject_id": "<tenant_id>",
  "reason": "Customer-initiated offboarding"
}
```

Requires `data_protection.erasure.propose` capability.  A second principal
with `data_protection.erasure.approve` capability must approve the request
before erasure proceeds.

---

### Step 4 — Check and release legal holds

Before deletion, verify no legal hold blocks the tenant:

```
GET /api/v1/data-protection/legal-holds
```

If holds exist, they must be released (or confirmed that legal retention
requirements are satisfied) before proceeding:

```
DELETE /api/v1/data-protection/legal-holds/{hold_id}
```

---

### Step 5 — Delete tenant (platform admin action)

There is currently no public API endpoint for hard tenant deletion.  This is a
deliberate safety gate: the platform administrator must perform the deletion
directly against the `tenants` table after confirming:

- All legal holds have been released.
- The DSAR erasure request has been fully applied.
- All channel configurations are in `disabled` status.
- The audit export has been verified and stored.

RLS enforcement means that once the tenant row is deleted (or its status is set
to `disabled`), the `operious_tenant_rls_allows` function will deny access to
all tenant-scoped rows for that tenant context.

---

### Step 6 — Rotate and revoke secrets

After data deletion:

1. **Webhook secrets** — rotate via `PUT /api/v1/tenant/channels/{config_id}`
   with a new `webhook_secret`, then disable the channel.
2. **Connector credential secrets** — propose a `credential_update` change
   request with zeroed-out credentials, then approve and apply it.
3. **Auth0 roles** — revoke the tenant operator's Auth0 application roles
   via the Auth0 Management API.  The Operious backend resolves authority from
   Auth0 claims; revoking roles at the identity provider is the authoritative
   revocation mechanism.

---

### Step 7 — Verify RLS: no rows visible after tenant deletion

After the tenant row is removed or disabled, run a verification query against
each FORCE RLS table from a connection whose `app.current_tenant_id` is set to
the deleted tenant's ID.  Every query must return zero rows.

The static invariant test at
`apps/backend/tests/test_rls_null_tenant_hardening.py` asserts that all FORCE
RLS tables have `tenant_id NOT NULL`, which guarantees that no NULL-tenant rows
can leak across the tenant boundary.

---

## 3. Capability Quick Reference

| Operation | Capability |
|---|---|
| Create tenant | `platform.tenant.admin` |
| Provision tenant admin | `platform.tenant.admin` |
| Configure channels | `tenant.channel.direct_apply` |
| Propose config changes | `tenant.config.write` |
| Approve config changes | `tenant.config.approve` |
| Apply config changes | `tenant.config.apply` |
| Upload knowledge | `tenant.knowledge.write` |
| Approve knowledge | `approvals.cases.approve` |
| Propose erasure request | `data_protection.erasure.propose` |
| Approve erasure request | `data_protection.erasure.approve` |
| Create legal hold | `data_protection.legal_hold.admin` |

---

## 4. Relevant Source Locations

| File | Purpose |
|---|---|
| `apps/backend/app/api/v1/routers/tenant.py` | Tenant lifecycle, channel, connector, and change-request endpoints |
| `apps/backend/app/api/v1/routers/knowledge.py` | Knowledge document ingest and search |
| `apps/backend/app/api/v1/routers/audit_export.py` | Audit export and integrity verification |
| `apps/backend/app/api/v1/routers/data_protection.py` | Erasure requests, legal holds, retention policies |
| `apps/backend/app/tenant/db/models.py` | `tenants`, channel, connector, and change-request ORM rows |
| `apps/backend/migrations/versions/0025_multi_tenant_production_hardening.py` | FORCE RLS enablement |
| `apps/backend/migrations/versions/0087_connector_configs_force_rls.py` | FORCE RLS on connector_configs |
| `apps/backend/tests/test_rls_null_tenant_hardening.py` | Static invariant test for RLS NOT NULL |
