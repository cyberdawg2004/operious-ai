# Operious AI — Data Retention and Deletion Policy

**Version:** 2026-07-05  
**Applies to:** All tenant data processed by the Operious AI production environment

---

## 1. Scope

This policy governs how long Operious AI retains customer data, when and how it is deleted, and the rights of data subjects to request erasure. Every retention period stated here is grounded in deployed code or database migrations.

---

## 2. Retention Periods by Data Category

### 2.1 Ticket Content (Session and Event Records)

**Tables:** `operational_sessions`, `session_events`, `execution_records`, `execution_attempts`

**Retention:** Session data is retained for the duration of the tenant relationship plus the tenant-configured retention period. The default retention period for LLM audit records is **90 days** (database default: `tenant_data_retention_policies.retention_days DEFAULT 90`, migration `0067_data_protection_controls`; application default: `DATA_PROTECTION_DEFAULT_RETENTION_DAYS=90` in `config.py`). Tenants can configure a different period via the data-protection API; any positive integer is accepted.

Session and event records that do not contain LLM-audit-linked content are retained for the duration of the tenant relationship and purged as part of tenant offboarding.

### 2.2 LLM Prompts and Completions

**Table:** `cognition_audit_records`

**Retention:** Per-tenant configurable; default **90 days** from `captured_at`. Purge is executed by `DataProtectionService.purge_expired_cognition_audits()` which reads `tenant_data_retention_policies` and deletes rows older than `retention_days` for each tenant (source: `app/data_protection/crypto.py`, method `purge_expired_cognition_audits`).

**Encryption:** `prompt_full` and `completion_full` are stored as `LargeBinary` encrypted with AES-256-GCM per-scope data keys. SHA-256 hashes (`prompt_sha256`, `completion_sha256`) are stored unencrypted for deduplication. The schema is defined in migration `0030_cognition_audit_records`.

**Legal hold block:** Purge is skipped for any tenant with an active legal hold (`DataProtectionService.has_active_legal_hold` check before delete).

### 2.3 Customer Attachments

**Storage:** AWS S3 (private bucket; `ATTACHMENTS_S3_BUCKET`)

**Retention:** **90 days** (`ATTACHMENT_RETENTION_DAYS=90` in `config.py`).

**Encryption:** Application-layer AES-256-GCM via `DataProtectionService.encrypt_bytes` before S3 upload. S3 SSE is defense-in-depth.

### 2.4 Webhook Nonces

**Table:** `webhook_nonce_records`

**Retention:** **24 hours** (`expires_at = received_at + 24h`). The schema enforces `expires_at > received_at` via a check constraint (migration `0028_webhook_nonce_records`). Expired rows are pruned by the maintenance worker (`worker_maintenance` process group, `webhook_maintenance` queue).

### 2.5 Action Grants and Idempotency Records

**Store:** Redis

**Retention:** Pre-approved agent action grants are valid for **1 hour** (`AGENT_PRE_APPROVED_DECISION_TTL_SECONDS=3600` in `config.py`) and consumed after a single use (one-time redemption via `pre_approved_decision_id`).

Survivability idempotency keys expire after **24 hours** (`SURVIVABILITY_IDEMPOTENCY_TTL_SECONDS=86_400` in `config.py`).

### 2.6 Rate-Limit and Quota Counters

**Store:** Redis

**Retention:** Fixed-window counters expire after the window (`RATE_LIMIT_WINDOW_SECONDS=60` in `config.py`). Quota counters have per-minute and per-hour windows.

### 2.7 Celery Task Results

**Store:** Redis result backend

**Retention:** **1 hour** (`CELERY_RESULT_EXPIRES_SECONDS=3600` in `config.py`).

### 2.8 Data-Protection Data Keys

**Table:** `data_protection_data_keys`

**Retention:** Data keys are retained for as long as encrypted data referencing them exists. A key is deleted only when the associated subject's erasure request is executed (see Section 3).

### 2.9 Legal Holds

**Table:** `data_protection_legal_holds`

**Retention:** Legal hold records are retained indefinitely until explicitly lifted by an authorized principal. Lifted holds retain their record with `lifted_at` set for audit purposes.

### 2.10 Erasure Request Records

**Table:** `data_protection_erasure_requests`

**Retention:** Erasure request records are retained indefinitely after execution to provide an audit trail of the erasure event.

---

## 3. Data Subject Access and Erasure (DSAR)

### 3.1 Erasure Request Process

Erasure is a dual-control operation implemented in `DataProtectionService` (`app/data_protection/crypto.py`):

1. **Propose:** `POST /api/v1/data-protection/erasure-requests` — requires `tenant.privacy.admin` capability. A new record with status `proposed` is created in `data_protection_erasure_requests`.

2. **Approve:** `POST /api/v1/data-protection/erasure-requests/{id}/approve` — requires `tenant.privacy.approve` capability. The approver **must differ** from the proposer (`ErasureRequestSeparationError` is raised otherwise). An active legal hold blocks approval and the request is rejected (`LegalHoldBlockedError`).

3. **Execute:** On approval, the subject's data key in `data_protection_data_keys` is deleted via `_delete_subject_key`. All ciphertext associated with that key ID becomes permanently unreadable ("crypto-erasure"). The request status advances to `executed` with `executed_at` recorded.

Direct erasure without dual-control is constitutionally rejected:
```python
async def erase_subject_key(self, *, tenant_id, subject_id, requested_by):
    raise DataProtectionError(
        "subject erasure requires dual-control propose/approve"
    )
```

### 3.2 Tenant Erasure

`DataProtectionService.erase_tenant_keys` deletes all data keys for a tenant. An active tenant-scope legal hold blocks this operation.

### 3.3 Legal Holds

`POST /api/v1/data-protection/legal-holds` — requires `tenant.privacy.admin` capability. A hold can be scoped to `tenant`, `subject`, or `session`. While a hold is active, automated purge and DSAR erasure are blocked.

---

## 4. Deletion Mechanisms

| Category | Mechanism |
|---|---|
| LLM audit records | `DataProtectionService.purge_expired_cognition_audits` (scheduled task) |
| Subject data keys | `DataProtectionService._delete_subject_key` on erasure approval |
| Tenant data keys | `DataProtectionService.erase_tenant_keys` on tenant offboarding |
| Webhook nonces | `worker_maintenance` pruning expired rows |
| Redis keys | TTL-based expiry (Redis `INCR+EXPIRE` pattern) |
| Celery results | `CELERY_RESULT_EXPIRES_SECONDS=3600` auto-expiry |

---

## 5. Retention Under Legal Hold

Any scheduled or DSAR-triggered deletion is blocked while an active legal hold covers the subject scope. The hold must be lifted by an authorized principal (`tenant.privacy.admin`) before deletion can proceed. Legal hold records themselves are never automatically purged.

---

## 6. Contact

For data retention questions, DSAR requests, or legal hold inquiries: `security@operious.com`
