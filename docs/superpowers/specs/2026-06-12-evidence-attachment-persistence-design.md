# Evidence Attachment Persistence (Phase 2a)

- **Date:** 2026-06-12
- **Status:** Approved (pending final user review of this document)
- **Sub-project:** Customer support autonomy — Phase 2 (evidence-based warranty/refund/
  replacement claims)
- **Depends on:** Phase 1 (autonomy threshold relaxation — merged), durable inbound ingress
  (`2026-06-09-durable-inbound-ingress-design.md`)
- **Owner:** backend

## 1. Context and goal

Phase 1 made informational refund/warranty/return replies auto-sendable when grounded and
risk-free. Phase 2's longer-term goal is to let Operious autonomously **execute** verified
warranty/refund/replacement claims based on evidence the customer sends (invoices, defect
photos), with human approval reserved for genuinely high-risk cases.

The prerequisite for any evidence-based verification (2b+) is durably storing the actual
bytes of inbound attachments — today they are **never persisted**. Email MIME attachments
are decoded transiently to compute `size_bytes` and then discarded
(`app/boundary/adapters/email_ses.py:_attachment_summary`); WhatsApp media messages are not
parsed at all — `attachments=()` is hardcoded in
`app/boundary/adapters/channel_webhooks.py:_normalize_meta`.

**Goal of 2a:** persist the bytes of email MIME attachments and WhatsApp media messages to
object storage, with a metadata row per attachment referencing the inbound ingress record.
No behavior change to replies, drafts, or governance — this is pure enrichment that 2b
(evidence extraction) will consume.

## 2. Non-goals

- Evidence extraction (OCR / vision-based reading of invoices or defect photos) — 2b.
- Any change to `_recommended_actions()`, claim-execution routing, or
  `TenantActionPolicy` — 2c+.
- Per-tenant object storage / bring-your-own-bucket — explicitly rejected (see ADR below);
  revisit only if a tenant contractually requires data residency in their own AWS account.
- Attachment retention/deletion policy automation — flagged as a fast follow once
  `customer_evidence_attachments` exists (the table includes the fields needed: `tenant_id`,
  `created_at`).

## 3. Architectural constraint that shapes this design

`app/boundary/adapters/base.py` documents a hard invariant: ingress adapters
(`BaseIngressAdapter.normalize`) **must be pure, synchronous translators — no I/O**.
Both pieces of work this spec needs (S3 upload, WhatsApp Graph API media fetch) are I/O.
Therefore **neither lives in an adapter**. Both happen in a new post-persistence stage of
`BoundaryIngressRuntime.ingest()` (`app/boundary/ingress/runtime.py`), which is already
`async` and already performs I/O (persistence).

Adapters only gain **data extraction** changes (still pure):
- WhatsApp: `_normalize_meta` learns to read `image`/`document`/`audio`/`video` message
  bodies and emit attachment *metadata* (media id, mime type, filename/caption, Meta-provided
  sha256) into `canonical_payload["attachments"]`. No network call.
- Email: unchanged — `_attachment_summary` already emits the metadata fields needed.

## 4. ADR: single platform-managed S3 bucket (not per-tenant)

SES credentials are per-tenant (each tenant supplies their own AWS keys). For evidence
storage we use **one operious-owned S3 bucket**, configured via new platform `Settings`
fields, with tenant isolation enforced by object-key prefix (`evidence/<tenant_id>/...`)
**and** by the `customer_evidence_attachments` row's `tenant_id` + RLS — not by IAM.

Rationale: per-tenant buckets would require every tenant to provision a bucket, grant their
existing SES IAM principal `s3:PutObject`/`s3:GetObject`, and add a bucket-name field to
channel config before evidence persistence works at all — meaning it silently does nothing
for every tenant onboarded before that extra step. A single platform bucket works for every
tenant from day one, centralizes encryption-at-rest/lifecycle/retention configuration, and
keeps the credential surface to one place. If a tenant later needs data residency in their
own AWS account, that's an additive per-tenant override, not a redesign.

## 5. Data flow

```
EMAIL                                          WHATSAPP
  │                                               │
  ▼                                               ▼
TenantEmailWebhookAdapter.normalize()      TenantWhatsAppWebhookAdapter.normalize()
  - parse_email_mime() (existing)            - _normalize_meta() (extended, still pure):
  - canonical_payload.attachments =             read message.image / .document / etc.
    [{filename, content_type,                   canonical_payload.attachments =
      content_id, disposition,                    [{media_id, content_type, filename?,
      size_bytes}, ...]   (unchanged)                caption?, sha256?}, ...]
  │                                               │
  └───────────────────┬─────────────────────────┘
                       ▼
        BoundaryIngressRuntime.ingest()
          1. normalize (above)
          2. replay classification (unchanged)
          3. event id derivation (unchanged)
          4. persist BoundaryIngressRecord (unchanged) → persisted_record.ingress_id
          5. NEW: if normalization.is_ok and canonical_payload["attachments"]:
               await self._evidence_attachments.ingest(
                   tenant_id=resolution.tenant_id,
                   ingress_id=persisted_record.ingress_id,
                   channel=<"email"|"whatsapp">,
                   attachments=canonical_payload["attachments"],
                   raw_email_bytes=request.payload.body   # email only
               )
               # never raises — failures become `failed` rows + log + metric
```

Step 5 is skipped entirely (no-op) if `self._evidence_attachments` is `None` — the default,
preserving today's behavior for any runtime that doesn't wire it up (e.g. voice, which this
spec explicitly excludes, matching the durable-ingress spec's precedent).

## 6. `EvidenceAttachmentIngestor`

New module: `app/boundary/ingress/evidence_attachments.py`.

```python
class EvidenceAttachmentIngestor:
    def __init__(
        self,
        *,
        storage: ObjectStorageClient,
        bucket: str,
        repository: EvidenceAttachmentRepository,
        whatsapp_media_fetcher: WhatsAppMediaFetcher,
    ) -> None: ...

    async def ingest(
        self,
        *,
        tenant_id: str,
        ingress_id: BoundaryIngressId,
        channel: str,
        attachments: Sequence[Mapping[str, Any]],
        raw_email_bytes: bytes | None,
    ) -> None:
        """Best-effort. Never raises — internal errors become `failed` rows."""
```

For each `(index, attachment)` in `enumerate(attachments)`:

1. **Resolve bytes:**
   - `channel == "email"`: `extract_email_attachment_bytes(raw_email_bytes, index)` (new
     helper, §7).
   - `channel == "whatsapp"`: `attachment["media_id"]` → `whatsapp_media_fetcher.fetch(
     tenant_id=tenant_id, media_id=...)` (§8). If `media_id` is missing (non-media message
     that still produced an `attachments` entry — shouldn't happen post-§9, but defensive),
     skip with `status="skipped"`, `error_code="no_media_id"`.
2. **Validate:**
   - size `<= settings.evidence_max_attachment_bytes` (default 25 MiB) → else
     `status="skipped"`, `error_code="attachment_too_large"`.
   - `content_type` (from attachment metadata, or Graph API response for WhatsApp) is in
     `_ALLOWED_EVIDENCE_CONTENT_TYPES` (`image/jpeg`, `image/png`, `image/webp`, `image/heic`,
     `application/pdf`) → else `status="skipped"`, `error_code="unsupported_content_type"`.
3. **Compute** `sha256 = hashlib.sha256(body).hexdigest()`. If the source already declared a
   sha256 (WhatsApp), mismatch → `status="failed"`, `error_code="sha256_mismatch"` (do not
   store — possible tamper/corruption).
4. **Upload:** `storage_key = f"evidence/{tenant_id}/{ingress_id}/{index}-{sanitized_filename}"`
   (`sanitized_filename` via new `sanitize_attachment_filename` — strips path separators,
   control chars, truncates to 128 chars, defaults to `"attachment"` if empty).
   `await storage.put_object(bucket=bucket, key=storage_key, body=body,
   content_type=content_type)`. On `ObjectStorageError` → `status="failed"`,
   `error_code="storage_put_failed"` (no row left half-written — see §10).
5. **Persist row** via `repository.record_attachment(...)` with the resolved `status`
   (`stored`/`skipped`/`failed`), `error_code`, and (if `stored`) `storage_bucket`,
   `storage_key`, `sha256`, `size_bytes`, `content_type`.

Any unexpected exception during steps 1-4 for a *single attachment* is caught, logged with
`ingress_id`/`tenant_id`/`index`, and recorded as a `failed` row with `error_code="internal_error"`
— it does not stop processing of the remaining attachments, and `ingest()` itself never
raises into `BoundaryIngressRuntime`.

## 7. Email: `extract_email_attachment_bytes`

New function in `app/boundary/adapters/email_ses.py`. Today `_text_and_attachments(message)`
walks MIME parts once and classifies each as text/html/attachment, calling
`_attachment_summary(part)` for attachments (in part-walk order). To guarantee the byte
extraction sees attachments in **exactly** the same order/filter as the metadata in
`canonical_payload["attachments"]` (index alignment is load-bearing — a mismatch would
attach the wrong file's bytes to the wrong metadata row), both will share one classification
helper:

```python
def _classify_parts(message: Message) -> tuple[list[Message], list[Message]]:
    """Returns (text/html parts in walk order, attachment parts in walk order)."""

def _text_and_attachments(message: Message) -> tuple[str | None, list[dict[str, Any]]]:
    _, attachment_parts = _classify_parts(message)
    ... # unchanged behavior, built from _classify_parts

def extract_email_attachment_bytes(raw_email: bytes, index: int) -> bytes | None:
    message = BytesParser(policy=policy.default).parsebytes(raw_email)
    _, attachment_parts = _classify_parts(message)
    if index >= len(attachment_parts):
        return None
    payload = attachment_parts[index].get_payload(decode=True)
    return payload if isinstance(payload, bytes) else None
```

This re-parses `raw_email` (cheap — already done once during `parse_email_mime`, and email
ingestion volume is low relative to the cost of a second parse) rather than threading
decoded bytes through the canonical (JSON-serialized, fingerprinted, persisted) payload.

## 8. WhatsApp: media message parsing + Graph API fetch

### 8a. Adapter change (pure, `channel_webhooks.py:_normalize_meta`)

After locating `first` (the first message object), before building the result:

```python
_MEDIA_MESSAGE_TYPES = ("image", "document", "audio", "video", "sticker")

message_type = _first_text(first.get("type"), "message")
attachments: tuple[dict[str, Any], ...] = ()
if message_type in _MEDIA_MESSAGE_TYPES:
    media = _mapping_or_none(first.get(message_type))
    if media is not None:
        media_id = _first_text(media.get("id"))
        if media_id is not None:
            attachments = ({
                "media_id": media_id,
                "content_type": _first_text(media.get("mime_type")),
                "filename": _first_text(media.get("filename")),
                "caption": _first_text(media.get("caption")),
                "sha256": _first_text(media.get("sha256")),
            },)
        if text is None:
            text = _first_text(media.get("caption"))
```

`attachments` is passed to `_ok_result(..., attachments=attachments, ...)` instead of the
hardcoded `()`. Twilio WhatsApp normalization (`_normalize_twilio`) is **out of scope** —
Twilio media uses `NumMedia`/`MediaUrl{N}` fields with a different fetch model
(pre-authenticated URLs, no token needed) and no tenant currently uses the Twilio path;
left as `attachments=()` with a code comment noting the gap for a future spec.

### 8b. `WhatsAppMediaFetcher`

New module: `app/boundary/ingress/whatsapp_media.py`.

```python
class WhatsAppMediaFetcher:
    def __init__(self, *, tenant_runtime: TenantRuntime, graph_api_base: str) -> None: ...

    async def fetch(self, *, tenant_id: str, media_id: str) -> WhatsAppMediaFetchResult:
        """Two-step Meta Graph API fetch. Raises WhatsAppMediaFetchError on failure."""
```

1. `credentials = await tenant_runtime.load_channel_credentials(tenant_id=tenant_id,
   channel_type=TenantChannelType.WHATSAPP)` → `business_token = credentials["business_token"]`
   (existing decrypted-credential path, `app/tenant/runtime.py:405`).
2. `GET {graph_api_base}/{media_id}` with `Authorization: Bearer {business_token}` →
   JSON `{"url": ..., "mime_type": ..., "file_size": ..., "sha256": ...}`. `graph_api_base`
   defaults to `https://graph.facebook.com/v21.0` (new `Settings.WHATSAPP_GRAPH_API_BASE_URL`).
3. `GET {url}` (the `lookaside.fbsbx.com` media URL) with the same `Authorization` header →
   raw bytes.

Both requests go through `create_isolated_http_client` with `PinnedIPAsyncHTTPTransport` and
`validate_public_https_url`, **same SSRF posture as `SesV2EmailSender`**
(`app/boundary/outbound/email_ses.py`). Host allowlist: the configured Graph API host plus
`lookaside.fbsbx.com` (Meta's media CDN — both are fixed, well-known Meta hosts, not
tenant-controlled).

`WhatsAppMediaFetchResult` carries `body: bytes`, `content_type: str | None`,
`sha256: str | None` (from step 2's JSON, used for the §6 step-3 integrity check alongside
any sha256 already present in the webhook payload).

## 9. Storage: `ObjectStorageClient` (in-house SigV4 S3, no boto3)

New module: `app/boundary/outbound/object_storage_s3.py`, modeled directly on
`SesV2EmailSender`'s SigV4 implementation (`app/boundary/outbound/email_ses.py:223-292`) —
same `_sigv4_headers`/`_signature_key`/`_hmac` structure, generalized for the S3 service
(`_SERVICE = "s3"`) and path-style requests (`https://s3.<region>.amazonaws.com/<bucket>/<key>`,
so the host-allowlist is the single regional host regardless of bucket name, matching the SES
pattern of one allowlisted host).

```python
@dataclass(frozen=True, slots=True)
class ObjectStoragePutResult:
    bucket: str
    key: str
    etag: str | None

class ObjectStorageError(Exception):
    def __init__(self, *, status_code: int, response_body: str) -> None: ...

class ObjectStorageClient(Protocol):
    async def put_object(
        self, *, bucket: str, key: str, body: bytes, content_type: str
    ) -> ObjectStoragePutResult: ...

    async def get_object(self, *, bucket: str, key: str) -> bytes: ...
    """get_object is unused by 2a but defined now — 2b (evidence extraction) needs it
    to read attachment bytes back, and defining the full read/write contract now avoids
    a second protocol-shape decision later."""

class S3ObjectStorageClient(ObjectStorageClient):
    def __init__(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        client: httpx.AsyncClient | None = None,  # test seam, SSRF gate still runs
    ) -> None: ...
```

`put_object` PUTs to `/{bucket}/{key}` with `x-amz-content-sha256` set to the real payload
hash (not `UNSIGNED-PAYLOAD`) and `x-amz-server-side-encryption: AES256` (SSE-S3, always
on — evidence may contain customer PII). `get_object` GETs the same path; a `404` raises
`ObjectStorageError(status_code=404, ...)`.

### New `Settings` fields (`app/core/config.py`)

| Field | Purpose |
|---|---|
| `EVIDENCE_S3_BUCKET` | Bucket name (path-style, no dots — required for SigV4 path-style + TLS) |
| `EVIDENCE_S3_REGION` | e.g. `us-east-1` |
| `EVIDENCE_S3_ACCESS_KEY_ID` / `EVIDENCE_S3_SECRET_ACCESS_KEY` | Platform AWS credentials, separate from any tenant SES credentials |
| `EVIDENCE_MAX_ATTACHMENT_BYTES` | default `26214400` (25 MiB) |
| `WHATSAPP_GRAPH_API_BASE_URL` | default `https://graph.facebook.com/v21.0` |

If `EVIDENCE_S3_BUCKET` is unset/empty, `EvidenceAttachmentIngestor` is not constructed and
`BoundaryIngressRuntime._evidence_attachments` stays `None` (step 5 no-ops) — lets this ship
and be enabled per-environment without a hard dependency on the bucket existing in every
deploy (e.g. local/dev).

## 10. Data model — migration `0085_customer_evidence_attachments`

New table `customer_evidence_attachments`, modeled on the RLS/grant pattern of
`0080_email_customer_reply_deliveries.py`:

| Column | Type | Notes |
|---|---|---|
| `attachment_id` | `uuid` | PK |
| `tenant_id` | `varchar(255)` | NOT NULL, FK → `tenants.tenant_id` ON DELETE RESTRICT, RLS |
| `ingress_id` | `uuid` | NOT NULL, FK → `boundary_ingress.ingress_id` ON DELETE CASCADE |
| `attachment_index` | `integer` | NOT NULL, position in `canonical_payload["attachments"]` |
| `channel` | `varchar(32)` | NOT NULL, `email` \| `whatsapp` |
| `status` | `varchar(16)` | NOT NULL, `stored` \| `skipped` \| `failed` |
| `error_code` | `text` | nullable |
| `filename` | `text` | nullable (sanitized) |
| `content_type` | `varchar(255)` | nullable |
| `size_bytes` | `bigint` | nullable (only set for `stored`) |
| `sha256` | `varchar(64)` | nullable (only set for `stored`) |
| `storage_bucket` | `varchar(255)` | nullable (only set for `stored`) |
| `storage_key` | `text` | nullable (only set for `stored`) |
| `created_at` | `timestamptz` | server default `now()` |

Constraints: `CHECK status IN ('stored','skipped','failed')`, `CHECK channel IN ('email','whatsapp')`,
`CHECK (status != 'stored') OR (storage_bucket IS NOT NULL AND storage_key IS NOT NULL AND
sha256 IS NOT NULL AND size_bytes IS NOT NULL)`, `CHECK length(sha256) = 64 OR sha256 IS NULL`,
`UNIQUE (tenant_id, ingress_id, attachment_index)`. RLS via `operious_tenant_rls_allows(tenant_id)`,
`FORCE ROW LEVEL SECURITY`, `GRANT SELECT, INSERT, UPDATE` to `operious_app`/`operious_app_test`
— same as `0080`.

`ON DELETE CASCADE` on `ingress_id` (unlike `0080`'s `RESTRICT` on its FKs): if a
`boundary_ingress` row is ever purged, its evidence rows (pointing at now-orphaned S3
objects) should go with it rather than block the delete. S3 object cleanup for cascaded
deletes is out of scope for 2a (no `boundary_ingress` deletion path exists today) but noted
for the retention-policy follow-up (§2).

## 11. Repository: `EvidenceAttachmentRepository`

Follows the existing persistence-layer split (`app/boundary/persistence/repository.py` /
`postgres.py` / `memory.py`): new `app/boundary/persistence/evidence_attachments.py` with
`EvidenceAttachmentRepositoryProtocol`, `PostgresEvidenceAttachmentRepository`, and
`InMemoryEvidenceAttachmentRepository` (for tests / runtimes without Postgres). One method:

```python
async def record_attachment(self, *, tenant_id, ingress_id, attachment_index, channel,
    status, error_code=None, filename=None, content_type=None, size_bytes=None,
    sha256=None, storage_bucket=None, storage_key=None) -> None
```

`INSERT ... ON CONFLICT (tenant_id, ingress_id, attachment_index) DO UPDATE` — idempotent,
since ingress replay-detection can in principle re-deliver the same `ingress_id` (defensive;
in practice a given `ingress_id` reaches step 5 at most once because step 4's persistence
already dedupes).

## 12. Wiring `BoundaryIngressRuntime`

`BoundaryIngressRuntime.__init__` gains `evidence_attachments:
EvidenceAttachmentIngestor | None = None` (keyword-only, defaults to `None` — every existing
construction site, including voice and tests, is unaffected). The runtime factory/wiring
module that constructs the email/WhatsApp ingress runtimes (found during implementation —
likely `app/boundary/runtime/factory.py` or equivalent app-startup wiring) constructs one
`EvidenceAttachmentIngestor` when `settings.EVIDENCE_S3_BUCKET` is non-empty and passes it to
those runtimes only (not voice).

Step 5 (§5) is inserted immediately after the existing persistence block
(`app/boundary/ingress/runtime.py:~404-426`), reading `persisted_record.ingress_id` and
`resolution.tenant_id`. `channel` is derived from `normalization.canonical_payload.get("channel")`
(already set to `"email"`/`"whatsapp"` by both adapters). `raw_email_bytes` is
`request.payload.body` when `channel == "email"`, else `None`.

## 13. Testing strategy

- **Unit — `object_storage_s3.py`**: SigV4 header correctness (golden values from AWS's
  published test vectors, same approach likely already used for SES's `_sigv4_headers` —
  verify), SSRF host-allowlist enforcement, `ObjectStorageError` on non-2xx.
- **Unit — `email_ses.py`**: `_classify_parts` ordering invariant — a multipart message with
  interleaved text/html/attachment parts produces attachment metadata
  (`_text_and_attachments`) and `extract_email_attachment_bytes(raw, i)` for the *same*
  `i` referring to the *same* part, across several MIME shapes (inline images via
  `Content-ID`, multiple attachments, attachment-before-body ordering).
- **Unit — `channel_webhooks.py`**: WhatsApp `image`/`document`/`audio`/`video`/`sticker`
  message bodies produce the expected `attachments` tuple; non-media `text` messages still
  produce `attachments=()`; a media message with no `id` produces `attachments=()`.
- **Unit — `whatsapp_media.py`**: two-step fetch happy path (mocked `httpx` transport, not a
  real Meta endpoint); Graph API error response → `WhatsAppMediaFetchError`; sha256 from
  step-2 JSON surfaces in `WhatsAppMediaFetchResult`.
- **Unit — `evidence_attachments.py` (`EvidenceAttachmentIngestor`)**: each branch in §6 —
  oversized → `skipped`/`attachment_too_large`; disallowed content type → `skipped`;
  sha256 mismatch → `failed`/`sha256_mismatch`; storage error → `failed`/`storage_put_failed`;
  happy path → `stored` row with correct `storage_key`/`sha256`/`size_bytes`; an exception
  in attachment 0 does not prevent attachment 1 from being processed.
- **Integration — `BoundaryIngressRuntime.ingest()`**: an email with one PDF attachment end
  to end produces a `boundary_ingress` row AND a `customer_evidence_attachments` row with
  `status='stored'`, correct `attachment_index=0`, and `storage_key` matching
  `evidence/<tenant_id>/<ingress_id>/0-<filename>`. A WhatsApp image message (mocked Graph
  API) produces the analogous row. An ingest with `evidence_attachments=None` (current
  default) is unaffected — existing tests continue to pass unchanged.
- **No production stub/mock paths**: `S3ObjectStorageClient` and `WhatsAppMediaFetcher` are
  fully implemented against the real S3 REST API / Graph API contracts. Test doubles
  (`InMemoryEvidenceAttachmentRepository`, mocked `httpx` transports in unit tests) are
  test-only, per [[feedback_no_mocks_production_grade]] — they never run in the
  `EvidenceAttachmentIngestor` construction path used by the app runtime.

## 14. Open items deferred to 2b+

- Evidence extraction (OCR/vision) reading `customer_evidence_attachments` rows.
- Attachment retention/expiry (S3 lifecycle rule + row cleanup).
- Twilio WhatsApp media (different fetch model — pre-authenticated `MediaUrl{N}`).
- Surfacing stored evidence in Command Center for human reviewers on escalated tickets.
