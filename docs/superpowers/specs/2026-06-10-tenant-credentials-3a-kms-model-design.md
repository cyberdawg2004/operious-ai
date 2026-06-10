# Tenant Credential Custody + KMS Foundation — Spec 3a

- **Date:** 2026-06-10
- **Status:** Approved in shape (pending final user review of this document)
- **Sub-project:** Tenant self-service channel setup (original task #6), backend-only
- **Decomposition:** 3a (this doc — KMS + credential model) → 3b (WhatsApp Embedded Signup)
  → 3c (SES managed + BYO)
- **Owner:** backend

## 1. Context

Tenant channel credentials already exist but are protected by a **local platform master
key**, not a cloud KMS:

- `app/tenant/credentials.py` — `TenantCredentialEncryptor`: AES-256-GCM, per-tenant key
  derived by HKDF from `TENANT_CREDENTIAL_MASTER_KEY` (a Fly secret), AAD = tenant id.
- `app/data_protection/crypto.py` — `MasterKeyRing` envelope: random data keys wrapped by
  a versioned local master (`OPDK1:` prefix, `_data_key_aad`).
- `app/tenant/db/models.py` — `TenantChannelConfigurationRow`: `credentials_enc`
  (LargeBinary), `webhook_secret`, rotation columns (`previous_credentials_enc`,
  `credential_rotated_at`, `credential_rotation_expires_at`), `status`, `verified_at`,
  unique `(tenant_id, channel_type)`. Current credential JSON is generic, e.g. Shopify
  `{"access_token": "shpat_…"}`.
- `operious-kms.json` is a provisioned **GCP service account** (project
  `operious-kms-81c603`) that **no code currently uses**.

So credentials are tenant-scoped and rotating, but "encrypt with KMS" is not yet true.
This spec wires real **GCP Cloud KMS** as the key-encryption authority, converges credential
encryption onto a KMS-backed envelope, defines typed per-channel credential schemas, and
formalizes the credential lifecycle — backend only, no UI.

## 2. Goals

1. Encrypt tenant credentials with a **KMS-backed envelope**: a random data key (DEK)
   encrypts the credential JSON; **GCP Cloud KMS wraps the DEK**.
2. Make the key-encryption authority a **pluggable seam** (`gcp` for prod, `local` for
   tests/dev and migration fallback) so the cloud dependency is swappable and testable.
3. **Migrate** existing credentials onto the new envelope without downtime (dual-read +
   one-shot re-encrypt).
4. Keep the governed **send path resilient**: cache decrypted DEKs in-memory (TTL),
   fail closed on KMS outage.
5. Define **typed per-channel credential schemas** (WhatsApp, SES-managed, SES-BYO,
   Shopify) validated before encryption.
6. Formalize the **credential lifecycle** (PENDING→VALIDATING→ACTIVE→FAILED/REVOKED) and a
   **validation seam** for live checks (implemented in 3b/3c).

## 3. Non-goals (out of scope for 3a)

- WhatsApp Embedded Signup OAuth token exchange + WABA/phone registration (**3b**).
- Live AWS SES domain-identity/DKIM provisioning + verification polling, and BYO
  cross-account assume-role execution (**3c**).
- Command Center self-service UI.
- Data-protection PII subsystem (DSAR/legal-hold/erasure) — unchanged; credentials are not
  subject data.

## 4. Architecture — KMS-backed envelope + provider seam

```
write:  credential JSON --(AES-256-GCM, DEK, AAD=tenant|channel)--> ciphertext
        DEK ------(CredentialKeyProvider.wrap_dek, AAD=tenant|channel)------> wrapped_dek
        store OPCRED2 container { wrapped_dek, nonce, ciphertext, kms metadata } in credentials_enc

read:   wrapped_dek --(CredentialKeyProvider.unwrap_dek, cached by wrapped-DEK hash, TTL)--> DEK
        ciphertext --(AES-256-GCM, DEK, AAD=tenant|channel)--> credential JSON --> validated model
```

**Provider seam** `CredentialKeyProvider`:
- `wrap_dek(plaintext_dek, *, tenant_id, channel) -> WrappedDekMetadata`
- `unwrap_dek(wrapped_dek_metadata, *, tenant_id, channel) -> bytes`

`WrappedDekMetadata` is structured and persisted in the credential envelope. It includes
the wrapping backend/provider, the GCP key resource or local key version, the wrapped DEK,
and provider metadata needed for decrypt, rotation, and audit. `CREDENTIAL_KMS_BACKEND`
selects the default provider for **new writes only**; decrypt always follows the provider
metadata embedded in the `OPCRED2` blob. Switching `CREDENTIAL_KMS_BACKEND=local` must not
attempt to decrypt a GCP-wrapped blob with the local provider.

Implementations, selected by `CREDENTIAL_KMS_BACKEND`:
- **`GcpCloudKmsKeyProvider`** (`gcp`, prod): `google-cloud-kms` Encrypt/Decrypt against
  `OPERIOUS_KMS_KEY_RESOURCE` (canonical; `GCP_KMS_KEY_RESOURCE` accepted only as a
  backwards-compatible alias), passing `tenant_id|channel` as KMS
  `additional_authenticated_data`, authenticated via `GOOGLE_APPLICATION_CREDENTIALS`
  (`operious-kms.json`, already provided by `prepare_google_credentials.sh`).
- **`LocalMasterKeyProvider`** (`local`, tests/dev + migration fallback): wraps the DEK
  with the existing `MasterKeyRing` master. No cloud dependency.

The AES-GCM layer also binds `tenant_id|channel` as AAD, so a credential blob cannot be
decrypted outside its tenant/channel scope even if the DEK leaked — matching the existing
`_aad`/`_data_key_aad` discipline.

### 4.1 Container format
A new versioned container `OPCRED2:` stored in `credentials_enc`:
`magic b"OPCRED2:" + json{ provider, key_resource, local_key_version,
provider_metadata, wrapped_dek(b64), nonce(b64), ciphertext(b64) }`. The old
`TenantCredentialEncryptor` magic remains decryptable for migration (see §5).

## 5. Migration of existing credentials

- **Dual-read decrypt:** if the blob starts with `OPCRED2:`, decrypt via the provider
  metadata embedded in that envelope; else decrypt via the legacy
  `TenantCredentialEncryptor` (HKDF) path. On the next write of that row, re-encrypt to
  `OPCRED2:`.
- **One-shot re-encrypt command:** a management script (mirroring Spec #2's
  dry-run-first backfill) that re-encrypts `credentials_enc` **and**
  `previous_credentials_enc` for all rows to `OPCRED2:`. **Dry-run by default** (reports
  candidate counts), `--apply` performs the migration, idempotent (skips rows already
  `OPCRED2:`), tenant-scoped, re-runnable. No plaintext is ever logged.

## 6. Read-path caching + fail-closed

Unwrapping a DEK calls Cloud KMS. To avoid a KMS call per governed send and to survive
brief KMS blips:
- In-process cache keyed by a hash of `wrapped_dek` → plaintext DEK, TTL
  `CREDENTIAL_DEK_CACHE_TTL_SECONDS` (default 300). Plaintext DEKs live in memory only,
  never persisted or logged.
- On cache-miss **and** KMS error → **fail closed** (raise a typed error; no send) rather
  than fall back to plaintext or skip encryption.

## 7. Typed per-channel credential schemas

A registry `channel_type → validated model`, validated before encryption and after decrypt:

- **WhatsApp**: current direct send shape `access_token, phone_number_id,
  graph_api_version` remains valid; future Embedded Signup shapes may add `waba_id,
  business_token, app_secret, verify_token`.
- **SES-managed**: `domain, region, identity_arn, dkim_tokens, mail_from_domain,
  verification_status`
- **SES current/direct**: `access_key_id/aws_access_key_id`,
  `secret_access_key/aws_secret_access_key`, `region/aws_region/ses_region`, optional
  `session_token`, `endpoint_url`, `configuration_set_name`
- **SES-BYO**: `role_arn, external_id, region`
- **Shopify**: `access_token` (existing shape, formalized)

3a defines the shapes + format validation; 3b/3c populate them through real flows.

## 8. Lifecycle + validation seam

Use the existing `TenantChannelConfigurationRow.status` + `verified_at`; 3a does not widen
the live `TenantChannelStatus` enum. The spec lifecycle maps to current states:
`PENDING/VALIDATING -> PENDING_VERIFICATION`, `ACTIVE -> ACTIVE`, `FAILED -> ERROR`, and
`REVOKED -> PAUSED`. A `ChannelCredentialValidator` interface (per channel type):
- 3a ships **format validation** (schema-shape + required fields) and the seam.
- 3b/3c ship **live validation** (Meta token check; SES identity/DNS check) that drives
  `VALIDATING → ACTIVE/FAILED` and sets `verified_at`.

Rotation (`previous_credentials_enc`, `credential_rotation_expires_at`) is preserved: both
current and previous blobs migrate to `OPCRED2:` and decrypt via dual-read.

## 9. Configuration / environment

```
CREDENTIAL_KMS_BACKEND=gcp                 # local for tests/dev
OPERIOUS_KMS_KEY_RESOURCE=projects/operious-kms-81c603/locations/<loc>/keyRings/<ring>/cryptoKeys/<key>
GCP_KMS_KEY_RESOURCE=...                   # optional legacy alias only
GOOGLE_APPLICATION_CREDENTIALS=...         # operious-kms.json (already wired)
CREDENTIAL_DEK_CACHE_TTL_SECONDS=300
TENANT_CREDENTIAL_MASTER_KEY=...           # retained for LocalMasterKeyProvider + migration fallback
```

## 10. Verification (real, TDD)

- `LocalMasterKeyProvider` wrap/unwrap round-trips; `GcpCloudKmsKeyProvider` round-trips
  (integration test gated on KMS creds, like the Postgres-gated tests).
- Envelope encrypt→decrypt round-trips a credential model; **wrong tenant/channel AAD fails
  decrypt**.
- **Dual-read**: a legacy `TenantCredentialEncryptor` blob and an `OPCRED2:` blob both
  decrypt; legacy re-encrypts to `OPCRED2:` on write.
- Re-encrypt command: dry-run changes nothing; `--apply` migrates and is idempotent on
  re-run; `previous_credentials_enc` migrated too.
- DEK cache: second decrypt of the same wrapped DEK does **not** call KMS; KMS outage +
  cache-miss **fails closed**.
- Typed schema validation rejects malformed credentials before encryption.
- Lifecycle transitions enforce legal moves; format validator gates `PENDING→VALIDATING`.
- The Cloud KMS client is the only I/O boundary that gets a test double.

## 11. Rollback

- `CREDENTIAL_KMS_BACKEND=local` changes only new writes to the local-master KEK. Existing
  GCP-wrapped `OPCRED2` blobs still require the embedded GCP provider metadata to decrypt.
- Dual-read keeps legacy blobs decryptable, so a half-migrated state is safe.
- The lifecycle/schema additions are additive; no destructive migration.

## 12. Operator actions

- Create the GCP Cloud KMS key ring + symmetric crypto key; grant the
  `operious-kms@…` service account `roles/cloudkms.cryptoKeyEncrypterDecrypter` on it.
- Set `GCP_KMS_KEY_RESOURCE` and `CREDENTIAL_KMS_BACKEND=gcp` as Fly secrets/env.
- Run the re-encrypt command dry-run, review, then `--apply`.

## 13. Hand-off to 3b / 3c

With 3a in place, 3b (WhatsApp Embedded Signup) and 3c (SES managed + BYO) only need to:
populate their typed schema via the real external flow, store it through the KMS envelope,
and implement the live `ChannelCredentialValidator` that drives `VALIDATING → ACTIVE`.
