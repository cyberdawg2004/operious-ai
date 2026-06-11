# Data-protection master key — GCP KMS custody (#54/#55)

When `DATA_PROTECTION_KMS_BACKEND=gcp`, the data-protection master key (the KEK
that wraps every per-row data key) is stored **KMS-wrapped** and unwrapped via
Google Cloud KMS at boot — it never sits at rest in plaintext. Unwrap failures
are fail-closed (the service refuses to boot rather than fall back to plaintext).

This reuses the same operator KMS key as tenant credentials
(`OPERIOUS_KMS_KEY_RESOURCE`).

## One-time: wrap the master key (KEK) with KMS

The KEK is 32 random bytes. The wrap MUST use the exact additional authenticated
data (AAD) the runtime uses to unwrap, or boot fails:

```
operious:data_protection:master_key:v1
```

```bash
# 1. Generate a 32-byte KEK (do this in a secure, audited environment).
head -c 32 /dev/urandom > kek.bin

# 2. Wrap it with your KMS key + the required AAD.
printf '%s' 'operious:data_protection:master_key:v1' > kek.aad
gcloud kms encrypt \
  --key "$OPERIOUS_KMS_KEY_RESOURCE" \
  --plaintext-file kek.bin \
  --ciphertext-file kek.enc \
  --additional-authenticated-data-file kek.aad

# 3. Base64 (standard, not url-safe) the wrapped ciphertext for the env var.
WRAPPED_B64="$(base64 -w0 kek.enc)"   # macOS: `base64 kek.enc | tr -d '\n'`

# 4. Securely destroy the plaintext KEK.
shred -u kek.bin kek.aad
```

## Configure (Fly secrets / env)

```
DATA_PROTECTION_KMS_BACKEND=gcp
DATA_PROTECTION_MASTER_KEYS=v1:<WRAPPED_B64>
DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION=v1
OPERIOUS_KMS_KEY_RESOURCE=projects/<PROJECT>/locations/global/keyRings/operious/cryptoKeys/<KEY>
GOOGLE_APPLICATION_CREDENTIALS=/path/to/operious-kms.json   # or OPERIOUS_KMS_SA_JSON on Fly
```

Production boot **fails closed** if `DATA_PROTECTION_KMS_BACKEND=local`, or if
`gcp` is set without a key resource / credentials (enforced by
`collect_production_problems`).

## Rotation

Add a new wrapped version (e.g. `v2:<WRAPPED_B64_2>`), set
`DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION=v2`, then run the existing
`DataProtectionService.rotate_master_key` rewrap path. The old version stays in
the ring until all rows are rewrapped (`unwrap` still resolves historical
versions).

## Verify (staging)

1. Set the env above on staging with a real KMS key + SA creds.
2. Boot: readiness must report READY (no `DATA_PROTECTION_KMS_BACKEND` problem).
3. Exercise an encrypt/decrypt path (e.g. a DSAR or a knowledge ingest) and
   confirm decryption succeeds — proving the KMS-unwrapped KEK is in use.
4. Capture the KMS decrypt audit-log entry as custody evidence.
