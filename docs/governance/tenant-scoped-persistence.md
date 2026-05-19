# Tenant-scoped persistence doctrine

> Wedge **2.75-ε** (point reads) + **2.75-ε extended** (query/list reads) +
> composition-root wiring of `expected_tenant_id` at the HTTP boundary.

## Constitutional guarantee

For every public read API on a tenant-scoped substrate
(session, coordination, supervisor, and any future tenant-scoped
backend), the following invariant holds:

> **A record persisted under tenant `T` is invisible to a caller whose
> request authority resolves to tenant `T'` ≠ `T`.**

Invisibility is **indistinguishable from non-existence** — point
reads return `None`, list reads return an empty page. This forecloses
cross-tenant ID-collision probing: an attacker authenticated as `T'`
cannot enumerate `T`'s records by guessing IDs and observing whether
the response distinguishes "not found" from "forbidden".

The contract is enforced at **two layers**:

| Layer | What enforces | How |
|---|---|---|
| Persistence | Row-level isolation in storage backend | `expected_tenant_id` keyword on every read method |
| Composition root | Cannot bypass at HTTP boundary | `app.dependencies.authority.require_tenant_scope` FastAPI dependency |

A handler that reads tenant-scoped persistence **MUST** source its
`expected_tenant_id` argument from the composition-root dependency.
The architectural invariant tests pin this at merge time.

## Persistence-layer contract

Every read method on every persistence protocol accepts an optional
keyword `expected_tenant_id: str | None = None`. The semantics are:

### Point reads (`get_*`)

```python
async def get_session(
    self,
    session_id: SessionId,
    *,
    expected_tenant_id: str | None = None,
) -> SessionRecord | None: ...
```

- `expected_tenant_id is None` → backward-compatible substrate-internal
  semantics (no scope clamp; substrate-internal reconstruction tools,
  cold-storage replay, admin endpoints).
- `expected_tenant_id is not None` and the record's `tenant_id`
  matches → return the record.
- `expected_tenant_id is not None` and the record's `tenant_id`
  differs → return `None` (indistinguishable from absence).

### Sub-record reads (events, correlations, findings, etc.)

Tenant scope **inherits from the owning apex record**. For example,
`get_event(event_id, expected_tenant_id="T")` returns `None` when the
event's owning session has tenant `T'` ≠ `T`. The implementation
typically looks up the parent (single dict lookup) before returning.

This preserves the doctrine without requiring every sub-record to
duplicate the `tenant_id` column — duplication would introduce
drift risk between sub-record and apex.

### Query / list reads

```python
async def list_sessions(
    self,
    query: SessionQuery,
    *,
    expected_tenant_id: str | None = None,
) -> SessionRecordPage: ...
```

`expected_tenant_id` is the **strict outer bound** applied BEFORE the
caller-supplied query filter:

1. Records not matching `expected_tenant_id` are filtered out first.
2. Then the caller's `query.tenant_id` and other filters are applied
   to the remaining set.
3. The caller cannot widen the scope by setting `query.tenant_id`
   to a different tenant — the intersection is empty.

This composes cleanly with single-tenant clients (`query.tenant_id`
typically duplicates `expected_tenant_id`, no behaviour change) and
admin clients (`query.tenant_id` may be `None`; results are clamped
to `expected_tenant_id` only).

## Backend implementation contracts

The reference in-memory implementation is canonical. Future
backends (Postgres / Elasticsearch / S3 / etc.) **MUST** match the
following observable semantics under the protocol contract.

### Postgres

- Every persistence table for tenant-scoped substrates has a
  `tenant_id` column (already present on the record dataclasses).
- Every read query MUST include `WHERE tenant_id = :expected_tenant_id`
  when `expected_tenant_id IS NOT NULL`.
- Sub-record reads MUST resolve the owning apex's `tenant_id` via
  a JOIN (preferred — single round-trip) or a separate parent fetch.
  Direct denormalisation of `tenant_id` onto sub-records is permitted
  if **and only if** the migration enforces parent-child invariants
  via a database trigger (the duplication-drift risk is otherwise
  unbounded).
- Row-Level Security (RLS) policies are **encouraged but not
  required**: they add defence-in-depth but do not substitute for the
  application-layer enforcement. Both layers must agree because
  Postgres RLS can be disabled by privileged roles; the application
  contract cannot.
- `expected_tenant_id is None` → no `WHERE` clause; substrate-internal
  reconstructors and admin endpoints get unconstrained reads.

### Elasticsearch

- Every document is indexed with a `tenant_id` field (keyword
  mapping; no analyzer).
- Every query is wrapped in a `bool { must: [..., { term: { tenant_id: T } }] }`
  filter when `expected_tenant_id IS NOT NULL`. The filter clause is
  preferred over `must` (no scoring contribution) but either is
  semantically equivalent.
- For aggregations, the same filter MUST be applied to the
  aggregation scope, not just the hit set — otherwise terms-aggregations
  leak the existence of other tenants' values.
- Index aliasing per-tenant is **discouraged** for this contract:
  it shifts isolation into routing config which lives outside the
  read API and cannot be tested by the persistence protocol's
  invariant suite.

### S3 / blob storage (cold-storage replay, archived records)

- Object keys SHOULD be prefixed with `{tenant_id}/` so a tenant's
  IAM policy can grant `s3:GetObject` only under its prefix.
- The application-layer read path MUST still validate the key's
  tenant prefix matches `expected_tenant_id` before returning the
  blob — IAM is defence-in-depth, not authorisation. (A
  presigned URL leak, a key-rotation race, or a misconfigured
  bucket policy would otherwise expose data.)
- Listing operations MUST honour the same prefix scope. List
  results are the equivalent of query/list reads and follow the
  strict-outer-bound rule above.

### Future backends

When introducing any new tenant-scoped persistence backend:

1. Implement the protocol's `expected_tenant_id` semantics exactly
   as specified above.
2. Add a regression test that mirrors
   `tests/test_tenant_scoped_persistence_reads.py` for the new
   backend (same record shapes, same scenarios, parametrised
   over the in-memory and new backend implementations).
3. Verify cross-tenant probing yields `None` / `()` and NOT an
   error / forbidden response.
4. Document the backend-specific enforcement (SQL `WHERE`, ES
   filter, S3 prefix) in this file's "Backend implementation
   contracts" section.

## Composition-root contract

Public HTTP read handlers source `expected_tenant_id` exclusively
through the canonical FastAPI dependencies in
`app.dependencies.authority`:

| Dependency | Returns | Use for |
|---|---|---|
| `require_tenant_scope` | `str` (non-empty) | All tenant-scoped reads. Default. |
| `request_tenant_scope_opt` | `str \| None` | Admin / cross-tenant reads. Justified per-endpoint. |
| `require_authority` | `AuthorityContext` | When the handler also needs the principal / org / env axes. |
| `request_authority_opt` | `AuthorityContext \| None` | Anonymous-allowed endpoints (health, marketing). |

`require_tenant_scope` enforces:

- 401 `authority_required` when the request is anonymous.
- 400 `tenant_axis_missing` when authority is present but carries
  no `tenant_id`.
- Returns the `tenant_id` as a `str` ready to forward verbatim into
  persistence reads.

### Why a dependency and not middleware

A middleware would couple every endpoint to the same tenant-scope
policy. Admin endpoints (cold-storage replay, ops dashboards) and
substrate-internal handlers legitimately span tenants. A
**dependency** makes the policy explicit at the handler signature,
visible in the route definition, and verifiable per-endpoint by
reviewers. Middleware is the wrong layer for a policy with
per-endpoint variance.

### Endpoint shape (future)

```python
@router.get("/sessions/{sid}")
async def get_session(
    sid: SessionId,
    runtime: SessionRuntime = Depends(get_session_runtime),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> SessionResponse:
    envelope = await runtime.get_session(
        sid, expected_tenant_id=expected_tenant_id
    )
    if not envelope.is_ok:
        # 2.75-ε returns "not found" indistinguishably from
        # "cross-tenant" — both surface as 404 at the HTTP layer.
        raise HTTPException(status_code=404)
    return SessionResponse.from_session(envelope.result)
```

Handlers MUST forward `expected_tenant_id` **verbatim**. They MUST
NOT widen, narrow, or substitute it. The composition root is the
single point of policy; the handler is a pass-through.

## Verification

The architectural invariants are pinned by:

| Test file | What it pins |
|---|---|
| `tests/test_tenant_scoped_persistence_reads.py` | Point + query reads enforce isolation across session, coordination, supervisor. |
| `tests/test_tenant_scope_dependency.py` | Composition-root dependency rejects anonymous / tenant-less authorities. |
| `tests/test_coordination_persistence.py` | Persistence contract round-trips. |
| `tests/test_session_persistence.py` | Persistence contract round-trips. |
| `tests/test_supervisor_persistence.py` | Persistence contract round-trips. |

When introducing a new backend, the suite MUST run against both
the in-memory reference and the new backend (parametrised), and
the test count MUST NOT decrease. Any test that "skips on backend
X" is a constitutional violation.

## Relationship to other doctrines

- **Authority propagation** (`authority-propagation.md`): tenant
  scope is one axis of the typed `AuthorityContext`. The
  composition-root dependency resolves *one* axis of the broader
  authority resolution doctrine.
- **Governance evaluation**: tenant scope is enforced **before**
  capability legality. Capability checks rely on a tenant having
  already been resolved (cf. `AuthorityContext` coexistence
  invariants from Wedge 2.75-γ).
- **Replay determinism**: tenant scope clamping is a strict filter
  applied to deterministic record sets; it preserves replay
  determinism because `expected_tenant_id=T` returns the same
  records on every invocation for the same persisted state.

## Open follow-ups

- Phase 2.4 substrate DI providers: wire `require_tenant_scope`
  into every constitutional-substrate read endpoint when those
  endpoints land.
- Backend rollout: implement the contract on Postgres /
  Elasticsearch / S3 backends per the contracts above.
- Audit-log substrate (planned Phase 3): apply the same
  tenant-scope contract; the audit trail itself is tenant-scoped.
