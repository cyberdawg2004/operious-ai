# Tenant Propagation Audit — Constitutional Doctrine

> **Status**: Read-only audit. Wedge B1 of Phase 1 (Enterprise Identity &
> Authority Infrastructure).
> **Scope**: Every `tenant_id` occurrence across `apps/backend/app/` (excluding
> `_deprecated/`) as of commit `d28e03c`.
> **Discipline**: This document is the **forensic baseline** for tenant
> authority. It introduces ZERO code, ZERO serializer mutation, ZERO
> governance mutation, ZERO persistence mutation. It exists to lock the
> understanding of the current surface before any Wedge B2+ touches the
> substrate.

---

## 0. Executive summary

The substrate already carries `tenant_id` through almost every value object
that crosses substrate boundaries (~95 source files, ~60 distinct field
declarations). However, the propagation is **structurally inconsistent**.
There is no single source of truth, no required ingress, and no centralised
resolver. Tenant authority is laundered through optional fields, opaque
metadata dicts, `or`-coalescing across multiple sources of truth, and
collapsing seed projections that erase the distinction between
`tenant_id=None` and `tenant_id=""`.

| Risk axis        | Current posture                                                          | Severity     |
|------------------|--------------------------------------------------------------------------|--------------|
| Authority        | No HTTP edge enforcement; multi-source coalescing without audit          | **CRITICAL** |
| Replay           | Two collision sites in deterministic UUID5 seeds (`tenant_id or ''`)     | **HIGH**     |
| Governance       | Two parallel tenant policing substrates with asymmetric defaults         | **HIGH**     |
| Chronology       | Trace types accept optional tenant; one substrate omits the field entirely | **MEDIUM**   |

The four governance/replay/chronology/authority risks combine into a single
constitutional violation that Wedge B2+ must address before any production
traffic touches the substrate: **`tenant_id` is the substrate's most-
referenced authority anchor and its least-defended one.**

---

## 1. Inventory — where `tenant_id` lives today

### 1.1 Numerical surface

* **~95 source files** under `apps/backend/app/` reference `tenant`
  (excluding `_deprecated/`).
* **~60 distinct `tenant_id: …` field declarations** across Pydantic
  models, frozen dataclasses, persistence records, traces, requests,
  results, contexts, and metadata enums.
* **0 files** under `apps/backend/app/api/` reference `tenant` of any
  kind.
* **0 middleware** under `apps/backend/app/middleware/` reference
  `tenant` of any kind.

### 1.2 Field-type universe

Every declared `tenant_id` field across the substrate uses exactly ONE
of these shapes:

| Shape                            | Count (approx) | Examples                                           |
|----------------------------------|----------------|----------------------------------------------------|
| `tenant_id: str \| None = None`  | ~45            | every request, context, trace, model field         |
| `tenant_id: str \| None`         | ~12            | every persistence record (required-but-nullable)   |
| `tenant_id: str` (positional)    | 0              | NONE — tenant is universally optional              |
| `tenant_id: TenantId`            | 0              | typed wrapper not yet adopted (Wedge A leaves this for B+) |

**Constitutional implication**: there is *no* substrate position today where
tenant_id is statically guaranteed to be present. Every read site MUST defend
against `None`.

---

## 2. Ingress surface — where `tenant_id` enters the substrate

### 2.1 HTTP edge (DR-1, CRITICAL)

`apps/backend/app/api/v1/routers/` contains ONE router: `health.py`.
`apps/backend/app/middleware/` contains ONE middleware that handles
request correlation only.

There is **NO** HTTP-level tenant extraction:

* No header parsing (e.g. `X-Tenant-Id`).
* No JWT claim extraction.
* No authentication / authorization tier whatsoever.
* No tenant routing middleware.
* The `RequestContextMiddleware` binds `X-Request-ID` only.

→ **Every `tenant_id` that exists today was minted by tests or test
harnesses, not by the HTTP edge.** The substrate has no notion of how
tenant_id will arrive in production.

### 2.2 Boundary contracts (current substrate-level ingress)

The closest thing to an "ingress" today is boundary contracts:

| File                                                             | Field                           | Risk  |
|------------------------------------------------------------------|---------------------------------|-------|
| `app/boundary/translation/contracts/requests.py:33`              | `IngressTranslateRequest.tenant_id` | OPTIONAL |
| `app/boundary/translation/contracts/requests.py:62`              | `EgressLocalizeRequest.tenant_id`   | OPTIONAL |
| `app/boundary/voice/contracts/requests.py:21`                    | `IngressTranscribeRequest.tenant_id`| OPTIONAL |
| `app/boundary/voice/contracts/requests.py:47`                    | `EgressSynthesizeRequest.tenant_id` | OPTIONAL |
| `app/boundary/models/source.py:37`                               | `BoundarySource.tenant_id`          | OPTIONAL |
| `app/session/contracts/requests.py:55`                           | `OpenSessionRequest.tenant_id`      | OPTIONAL |
| `app/arbitration/contracts/requests.py:33`                       | `CaseFilingRequest.tenant_id`       | OPTIONAL |
| `app/coordination/contracts/requests.py:107`                     | `CoordinationDispatchRequest.tenant_id` | OPTIONAL |
| `app/coordination/topology/contracts/requests.py:69-71`          | `CoordinationTopologyEvaluationRequest.{tenant_id, sender_tenant_id, recipient_tenant_id}` | OPTIONAL |
| `app/coordination/policy/contracts/requests.py:78-80`            | `CoordinationPolicyEvaluationRequest.{tenant_id, sender_tenant_id, recipient_tenant_id}` | OPTIONAL |
| `app/supervisor/contracts/requests.py:67`                        | `ExecutionInspectionRequest.tenant_id` | OPTIONAL |
| `app/hardening/contracts/requests.py:148`                        | hardening request `tenant_id`       | OPTIONAL |
| `app/organizational_intelligence/contracts/requests.py:49,75,96,110,136,204,245` | seven OI request shapes        | OPTIONAL |

### 2.3 The "source-as-authority" inversion (BS-1)

`BoundarySource.tenant_id` is unusual: in `boundary/ingress/runtime.py`
lines `176, 199, 219, 326, 443, 483, 521`, the runtime reads
`request.source.tenant_id` — tenant_id is structurally a property of the
*configured endpoint*, not the request payload.

This is **defensible** (an endpoint is one tenant's endpoint), but it
inverts the dependency: authority follows configuration. In production
this becomes the de-facto ingress: whoever owns endpoint registration
owns tenant binding. **Wedge B+ should make this explicit, not implicit.**

---

## 3. Propagation map — substrate by substrate

Each subsection lists: where `tenant_id` is *carried*, where it is
*resolved/merged*, where it is *dropped*, and where it is *stored*.

### 3.1 `app/boundary/`

**Carrier value objects**

* `BoundarySource.tenant_id` — `models/source.py:37`
* `BoundaryReplayRecord.tenant_id` — `models/replay.py:64`
* `BoundaryIdentityBundle.tenant_id` (voice) — `voice/models/identity_bundle.py:23`
* `TranslationIdentity.tenant_id` — `translation/models/identity.py:23`
* `BoundaryTrace.tenant_id` — `tracing.py:47, 72`
* Translation/voice traces — `translation/traces/trace.py:21,39`, `voice/traces/trace.py:21,39`

**Resolution sites**

* `boundary/ingress/runtime.py` reads from `request.source.tenant_id`
  (NOT `request.tenant_id` — distinct).
* `boundary/translation/{ingress,egress}/runtime.py` reads from
  `request.tenant_id` directly.
* `boundary/voice/{ingress,egress}/runtime.py` reads from
  `request.tenant_id` directly.

**Replay-key derivation (CO-1, HIGH)**

`boundary/identity.py:88-114` `derive_event_id` and lines `133-153`
`derive_replay_key` both project `tenant_id` through `tenant_id or ''`:

```
seed = f"{source_type}|{tenant_id or ''}|{external_message_id}"
```

→ **Constitutional violation**: a tenantless event and an explicit
`tenant_id=""` event hash to the **same** event_id and the **same**
replay_key. Two distinct authority states project to one identifier.
This is the same `tenant_id or ''` pattern flagged in §3.2 for session.

**Storage**: `BoundaryReplayRecord` (records.py:34, 66) stores
`tenant_id: str | None`. Persistence memory filters via
`r.tenant_id == query.tenant_id` (memory.py:114, 150) — `None` matches `None`,
which is correct equality but is *not* tenant isolation.

### 3.2 `app/session/`

**Carrier value objects**

* `SessionIdentity.tenant_id` — `models/identity.py:39`
* `SessionTrace.tenant_id` — `traces/trace.py:44, 64`
* `SessionRecord.tenant_id` — `persistence/records.py:31`

**Authority flow**

`SessionRuntime.open_session()` (`runtime/runtime.py:182`) reads
`request.tenant_id` and constructs `SessionIdentity(tenant_id=…)`. The
identity is then the canonical authority anchor for the session.

After open, every internal call reads from `session.identity.tenant_id`
(`runtime.py:316, 444, 541, 652, 718, 774, 985, 1087`). This is the
**correct propagation pattern** the rest of the substrate should mirror:
ingress once → authority anchor on the apex value object → every
downstream read goes through the anchor.

**Replay-key derivation (CO-2, HIGH)**

`session/identity/__init__.py:103-129` `derive_session_id`:

```
seed = f"{scope}|{tenant_id or ''}|{principal_id or ''}|{external_handle}"
```

→ Same `tenant_id or ''` collision as boundary. Tenantless and `tenant_id=""`
sessions collapse to the same `SessionId`.

**Canonical serialisation**

`session/serializers/canonical.py:116` projects
`session.identity.tenant_id` into the canonical session dict. Because
`canonicalize_payload` is now `_string_key`-projecting (Phase 0,
Cluster A), serialisation is replay-safe — but only conditional on the
identity having been populated correctly upstream.

### 3.3 `app/governance/`

**Carrier value objects**

* `GovernanceContext.tenant_id` — `context.py:66`
* `RetrievalGovernanceSubject.tenant_id` — `subjects/retrieval.py:92`
* `ExecutionGovernanceSubject.tenant_id` — `subjects/execution.py:51`
* `CommunicationGovernanceSubject.tenant_id` — `subjects/communication.py:79`
* `AgentActionGovernanceSubject.tenant_id` — `subjects/agent_actions.py:60`
* `GovernanceTrace.tenant_id` — `tracing.py:64`
* `GovernanceDecisionRecord.tenant_id` — `persistence/records.py:204`
* `GovernancePersistenceModel.tenant_id` — `persistence/models.py:27`

**Resolution helper (RH-1, single source of resolution doctrine)**

`governance/policies/builtin.py:328-339` defines
`_tenant_id_for(context) -> str | None`:

```python
def _tenant_id_for(context: GovernanceContext) -> str | None:
    subject = context.subject
    typed_tenant = getattr(subject, "tenant_id", None)
    if typed_tenant is not None:
        return typed_tenant
    return context.tenant_id
```

* **It is private** (underscore-prefixed).
* **It is the only centralised tenant resolver in the substrate.**
* **Its resolution policy** is: prefer typed subject, fall back to context.
* It is **not** referenced from any sibling substrate.

→ Constitutional implication: every other substrate has its own ad-hoc
resolution (see §3.4–§3.9). The doctrine is correct; the
implementation is sequestered in one private helper inside one policy
module.

**Authority enforcement (AP-1)**

`TenantScopePolicy` (`policies/builtin.py:52-140`):

* **ALLOWs** any tenant when `allowed_tenants` is empty (`open_allowlist`
  rule). After Phase 0, the result carries
  `metadata={"permissive_default": True, "config_missing": "allowed_tenants"}`
  for forensic visibility, but the **decision** is still ALLOW.
* **DENYs** when `tenant_id is None` and `allowed_tenants` is non-empty
  (`tenant_missing` rule).
* **DENYs** when `tenant_id` is not in the allowlist.

→ **Asymmetry with `MaxQueryLengthPolicy`**: after Phase 0, `MaxQueryLengthPolicy`
DENIes when `query` is missing (Core Law 4, fail-closed). But
`TenantScopePolicy` still ALLOWs when the configuration (`allowed_tenants`) is
missing. **This is a knowing trade-off documented in the file**, but it means
the substrate's tenant defence is "operator-explicit opt-in", not "operator-
explicit opt-out". Wedge B+ should consider flipping the default once production
configuration is wired.

**Persistence**

`governance/persistence/serializers.py:93` stores
`tenant_id=trace.tenant_id` into the decision record. Memory backend
filters with `record.tenant_id == query.tenant_id` (memory.py:118).

### 3.4 `app/agents/`

**Carrier value objects**

* `AgentExecutionContext.tenant_id` — `context.py:49`
* `AgentExecutionRecord.tenant_id` — `persistence/records.py:125`

**The agent trace omission (DR-2, CRITICAL)**

`AgentExecutionTrace` in `tracing.py` has **NO** `tenant_id` field.
Confirmed: `grep tenant apps/backend/app/agents/tracing.py` → 0 matches.

To preserve tenant_id across the live-envelope/trace path, the runtime
**stuffs tenant_id into the trace metadata dict**:

`agents/runtime/runtime.py:240-247`:

```python
metadata={
    …
    "tenant_id": tenant_id,
    **(dict(metadata or {})),
},
```

The persistence serializer **fishes it back out** of the opaque metadata:

`agents/persistence/serializers.py:66`:

```python
tenant_id=tenant_id if tenant_id is not None else trace.metadata.get("tenant_id"),
```

The supervisor view-builder **also fishes it back out**:

`supervisor/runtime/view_builder.py:76`:

```python
effective_tenant = (
    tenant_id
    if tenant_id is not None
    else _safe_str(trace.metadata.get("tenant_id"))
)
```

→ **Two parallel re-extractors** of the same authority field from the
**same opaque metadata dict**, in two substrates, with no schema
guaranteeing the field exists or its value type. **This is the single
most fragile authority site in the substrate.**

**Tool invocation propagation (TI-1, defensible pattern)**

`agents/tools/invoker.py:276, 284` injects
`tenant_id=context.tenant_id` into the governance subject before
evaluating. This is the **single clean propagation** site
where tenant_id flows from agent execution into governance — and it
relies on `AgentExecutionContext.tenant_id` (typed) rather than the
metadata fishing. This is the pattern other substrates should adopt.

### 3.5 `app/coordination/`

**Carrier value objects**

* `CoordinationDispatchRequest.tenant_id` — `contracts/requests.py:107`
* `CoordinationEnvelope.tenant_id` — `envelopes.py:108`
* `CoordinationRecipient.tenant_id` — `models/recipients.py:50`
* `CoordinationParticipant.tenant_id` — `models/participants.py:40`
* `CoordinationTrace.tenant_id` — `tracing.py:86, 122`
* `CoordinationRecord.tenant_id` — `persistence/records.py:70`
* Topology: `topology/models/node.py:49`, `topology/contracts/{requests,results}.py`, `topology/persistence/records.py:111`, `topology/tracing.py:59, 92`
* Policy: `policy/contracts/{requests,results}.py:78,114`, `policy/persistence/records.py:209`, `policy/persistence/models.py:30`, `policy/tracing.py:58, 97`

**Resolution sites (DR-4, HIGH)**

`coordination/runtime/runtime.py` performs `or`-coalescing at **eight**
sites:

| Line  | Pattern                                                          |
|-------|------------------------------------------------------------------|
| 501   | `tenant_id=request.tenant_id or msg.recipient.tenant_id`         |
| 597   | `tenant_id=request.tenant_id or msg.recipient.tenant_id`         |
| 703   | `tenant_id=request.tenant_id or msg.recipient.tenant_id`         |
| 739   | `tenant_id=request.tenant_id or msg.recipient.tenant_id`         |
| 971   | `tenant_id=request.tenant_id or msg.recipient.tenant_id`         |
| 502/598| `sender_tenant_id=request.tenant_id`                           |
| 503/599| `recipient_tenant_id=msg.recipient.tenant_id`                  |

→ **Three constitutional issues**:
1. `or` semantics collapse an explicit empty string (`""`) to the
   recipient's tenant — a tenantless sender becomes the recipient's
   tenant **silently**, no trace event emitted.
2. The merged single-tenant `tenant_id` is what gets persisted in
   `CoordinationRecord.tenant_id`. The directional
   `sender_tenant_id` and `recipient_tenant_id` are persisted on the
   *policy* and *topology* records only. → Replay reconstruction can
   recover the directional pair from those records, but the
   `CoordinationRecord` itself only knows the merged single tenant.
3. There is no audit emission stating *which source the merged
   tenant_id came from*. Forensic queries cannot distinguish "request
   carried tenant" from "recipient carried tenant" without joining
   across substrates.

**Authority enforcement (AP-3, HIGH — divergent policing)**

`coordination/policy/evaluators/builtin/tenant_isolation.py` defines
**`TenantIsolationEvaluator`**. Its semantics differ from
`governance.TenantScopePolicy`:

| Axis                              | `governance.TenantScopePolicy`              | `coordination.TenantIsolationEvaluator`     |
|-----------------------------------|---------------------------------------------|---------------------------------------------|
| Default when unconfigured         | ALLOW (open allowlist)                      | DENY (`require_tenant=True` is default)     |
| Reads from                        | `_tenant_id_for(context)`                   | `request.tenant_id`, `request.sender_tenant_id`, `request.recipient_tenant_id` |
| Notion of "tenant"                | Single tenant scope                         | Pair: sender + recipient                    |
| Cross-tenant authorisation        | Not in scope                                | Explicit allowlist of pairs                 |
| Substrate location                | Governance substrate                        | Coordination policy substrate               |

→ **Two parallel tenant-policing systems**. They share no code. They use
opposite defaults. They disagree on what "tenant" means. Wedge B+ must
decide whether to unify them or keep them deliberately separate (with
explicit documentation of the asymmetry).

### 3.6 `app/arbitration/`

**Carrier value objects**

* `ArbitrationCase.tenant_id` — `models/case.py:77`
* `CaseFilingRequest.tenant_id` — `contracts/requests.py:33`
* `CaseFilingResult.tenant_id` — `contracts/results.py:88`
* `ArbitrationTrace.tenant_id` — `tracing.py:39, 62`
* `ArbitrationCaseRecord.tenant_id` — `persistence/records.py:95`
* `ArbitrationPersistenceModel.tenant_id` — `persistence/models.py:27`

**Resolution**: Three sites in `arbitration/runtime/runtime.py:250, 285,
517` all read `tenant_id=request.tenant_id` cleanly. Single-source
propagation. No `or`-coalescing. **Constitutionally clean.**

### 3.7 `app/supervisor/`

**Carrier value objects**

* `ExecutionInspectionRequest.tenant_id` — `contracts/requests.py:67`
* `ExecutionInspectionResult.tenant_id` — `contracts/results.py:44`
* `InspectionView.tenant_id` — `models/view.py:94`
* `SupervisorTrace.tenant_id` — `tracing.py:56`
* `SupervisorExecutionInspectionRecord.tenant_id` — `persistence/records.py:246`

**Resolution sites (DR-3, HIGH)**

`supervisor/runtime/runtime.py:163-167`:

```python
effective_tenant_id = (
    request.tenant_id
    if request.tenant_id is not None
    else view.tenant_id
)
```

→ Two-source coalescing. Better than coordination's `or` (it uses
`is not None` so empty string survives), but **still silently merges
authority sources without emitting a trace event identifying the
source**.

`view_builder.py:73-77` and `143-145` apply the same pattern.

**Replay**: the `view.tenant_id` itself is sourced from the agent
execution's `trace.metadata.get("tenant_id")` (DR-2). Therefore the
"effective tenant" the supervisor stamps onto its trace can be
**downstream of the metadata laundering**. If the agent runtime ever
fails to stuff tenant_id into metadata, the supervisor view silently
becomes tenantless.

### 3.8 `app/hardening/`

**Carrier value objects**

* `HardeningRequest.tenant_id` — `contracts/requests.py:148`
* `HardeningAuditRecord.tenant_id` — `models/audit.py:34`
* `HardeningFailure.tenant_id` — `models/failure.py:60`
* `HardeningTrace.tenant_id` — `traces/trace.py:21, 38`

**Resolution**: `hardening/validation/runtime.py:658` does
`tenant_id = getattr(request, "tenant_id", None)` — defensive `getattr`
because the same code path handles multiple request shapes. Then
line 548, 679 read `request.tenant_id` directly. **Mostly clean** but
the `getattr` site signals that the validation runtime accepts
heterogeneous request shapes — fragile if a new request type forgets
the field.

### 3.9 `app/organizational_intelligence/`

**Carrier value objects (the most pervasive substrate, ~24 declarations)**

Models: `pattern.py:42`, `sop.py:84`, `tonality.py:50`,
`communication.py:56`, `recommendation.py:55`, `memory.py:84, 177, 279`.

Traces: `traces/trace.py:25, 45`.

Persistence queries: `persistence/queries.py:41, 58, 76, 93` (four
distinct query types, each with optional `tenant_id`).

Identity helpers: `identity/__init__.py:182, 253` accept
`tenant_id: str | None` in deterministic derivation seeds — same
collapse risk as boundary/session.

**Resolution sites**: ~40+ call sites across
`communication/runtime.py`, `training/runtime.py`, `sop/runtime.py`,
`recommendations/runtime.py`, `tonality/runtime.py`. All read
`request.tenant_id` directly with no coalescing. Single-source.
Constitutionally clean per substrate but **proliferates the
"tenant_id is optional" assumption** further than any other.

### 3.10 `app/observability/`

`observability/governance_metrics.py:33` and
`observability/governance_logging.py:34` emit `tenant_id` in their
payload. **Only governance** emits tenant_id in observability today —
coordination, supervisor, arbitration, session, hardening, and
organizational_intelligence observability sites do not.

→ **OBS-1**: tenant_id is invisible to operational dashboards for every
substrate except governance.

---

## 4. Persistence storage — what survives a restart

Every substrate persists `tenant_id` as `str | None` (NEVER `str`).
Records:

| Substrate                | Record                                         | File:Line |
|--------------------------|------------------------------------------------|-----------|
| Boundary (event)         | `BoundaryEventRecord.tenant_id`                | `boundary/persistence/records.py:34` |
| Boundary (egress)        | `BoundaryEgressRecord.tenant_id`               | `boundary/persistence/records.py:66` |
| Boundary (replay)        | `BoundaryReplayRecord.tenant_id`               | `boundary/models/replay.py:64` |
| Session                  | `SessionRecord.tenant_id`                      | `session/persistence/records.py:31` |
| Governance               | `GovernanceDecisionRecord.tenant_id`           | `governance/persistence/records.py:204` |
| Agents                   | `AgentExecutionRecord.tenant_id`               | `agents/persistence/records.py:125` |
| Coordination             | `CoordinationRecord.tenant_id`                 | `coordination/persistence/records.py:70` |
| Coordination topology    | `CoordinationTopologyRecord.tenant_id`         | `coordination/topology/persistence/records.py:111` |
| Coordination policy      | `CoordinationPolicyEvaluationRecord.tenant_id` | `coordination/policy/persistence/records.py:209` |
| Arbitration              | `ArbitrationCaseRecord.tenant_id`              | `arbitration/persistence/records.py:95` |
| Supervisor               | `SupervisorExecutionInspectionRecord.tenant_id`| `supervisor/persistence/records.py:246` |
| Hardening                | `HardeningAuditRecord.tenant_id`               | `hardening/models/audit.py:34` |
| OI (SOP)                 | `SopRecord.tenant_id`                          | `organizational_intelligence/models/sop.py:84` |
| OI (Recommendation)      | `RecommendationRecord.tenant_id`               | `organizational_intelligence/models/recommendation.py:55` |
| OI (Communication)       | `CommunicationRecord.tenant_id`                | `organizational_intelligence/models/communication.py:56` |

Memory-backed query filters (all substrates that have them) use
`record.tenant_id == query.tenant_id`. This is *equality*, not
*isolation*: a `query.tenant_id=None` returns every tenantless record
regardless of operator intent. Production-grade tenant isolation needs
to forbid `None` matching by default.

---

## 5. Defects classified by risk axis

### 5.1 AUTHORITY RISK (top severity)

| ID    | Site                                                                 | Severity | Description |
|-------|----------------------------------------------------------------------|----------|-------------|
| DR-1  | `app/api/v1/`, `app/middleware/`                                     | CRITICAL | No HTTP-edge tenant extraction. No middleware. No auth tier. tenant_id today is entirely fabricated by internal callers. |
| DR-2  | `app/agents/tracing.py` (no field) + `agents/runtime/runtime.py:244` + `agents/persistence/serializers.py:66` + `supervisor/runtime/view_builder.py:76` | CRITICAL | `AgentExecutionTrace` has no `tenant_id` field. Authority is stuffed into / fished out of opaque `metadata["tenant_id"]` by three different sites. Two re-extractors of the same field from the same opaque dict in two substrates. |
| DR-3  | `supervisor/runtime/runtime.py:163-167`, `view_builder.py:73-77, 143-145` | HIGH     | Two-source coalescing (`request.tenant_id` vs `view.tenant_id`) without trace event identifying the source. |
| DR-4  | `coordination/runtime/runtime.py:501, 597, 703, 739, 971`            | HIGH     | `or`-coalescing of `request.tenant_id` and `msg.recipient.tenant_id`. `""` collapses to the recipient tenant silently. No source-of-truth trace. |
| AP-1  | `governance/policies/builtin.py:92-105` `TenantScopePolicy.open_allowlist` | HIGH     | Empty allowlist → ALLOW (with `permissive_default` tag, but still ALLOW). Asymmetric with `MaxQueryLengthPolicy.query_missing` (DENY). |
| AP-3  | `coordination/policy/evaluators/builtin/tenant_isolation.py` vs `governance/policies/builtin.py` | HIGH     | Two parallel tenant-policing systems with opposite defaults, different reads, different notions of "tenant". |
| RH-1  | `governance/policies/builtin.py:328-339` `_tenant_id_for`            | MEDIUM   | Only centralised tenant resolver in the codebase. Private. Not callable from other substrates. Every other substrate reinvents resolution ad-hoc. |
| BS-1  | `boundary/models/source.py:37` + `boundary/ingress/runtime.py:176, 199, 219, 326, 443, 483, 521` | MEDIUM | Tenant authority sourced from configured `BoundarySource`, not request. Authority follows configuration — defensible but implicit. |

### 5.2 REPLAY RISK

| ID    | Site                                                                 | Severity | Description |
|-------|----------------------------------------------------------------------|----------|-------------|
| CO-1  | `boundary/identity.py:111-114, 150-153` (`derive_event_id`, `derive_replay_key`) | HIGH | `f"…|{tenant_id or ''}|…"` collapses tenantless and `tenant_id=""` to identical UUID5. Two distinct authority states project to one identifier. |
| CO-2  | `session/identity/__init__.py:125-128` (`derive_session_id`)         | HIGH     | Same `tenant_id or ''` collapse for session id derivation. |
| CO-3  | `organizational_intelligence/identity/__init__.py:182, 253`          | HIGH     | Two more deterministic derivation functions accept `tenant_id: str | None` in their seeds — same collapse risk pending verification of their seed string construction. |
| DR-2 (reprise) | metadata laundering of tenant_id in agent traces            | HIGH     | Replay of an agent execution depends on `metadata["tenant_id"]` surviving canonicalisation. Today it does (after Phase 0), but the *type* of the value in the dict is `str | None` from a Python perspective — if the metadata key is ever set to a non-str value, replay reconstruction silently rewrites authority. |

### 5.3 CHRONOLOGY RISK

| ID    | Site                                                                 | Severity | Description |
|-------|----------------------------------------------------------------------|----------|-------------|
| TR-1  | Every substrate trace                                                 | MEDIUM   | 13 trace types accept `tenant_id: str | None = None` (`boundary/tracing.py:47,72`, `boundary/translation/traces/trace.py:21,39`, `boundary/voice/traces/trace.py:21,39`, `session/traces/trace.py:44,64`, `arbitration/tracing.py:39,62`, `coordination/tracing.py:86,122`, `coordination/topology/tracing.py:59,92`, `coordination/policy/tracing.py:58,97`, `hardening/traces/trace.py:21,38`, `organizational_intelligence/traces/trace.py:25,45`, `supervisor/tracing.py:56`, `governance/tracing.py:64`). Adjacent timeline events for the same authority chain may carry differing tenant_id values without any check. |
| TR-2  | `app/agents/tracing.py`                                              | MEDIUM   | `AgentExecutionTrace` has no `tenant_id` field at all — the only substrate trace that omits it. Chronology reconstruction must reach into `metadata` to discover authority. |

### 5.4 GOVERNANCE RISK

| ID    | Site                                                                 | Severity | Description |
|-------|----------------------------------------------------------------------|----------|-------------|
| AP-1  | `TenantScopePolicy.open_allowlist`                                    | HIGH     | Permissive default. After Phase 0 it carries a `permissive_default` audit tag, but the *decision* is still ALLOW. Production must flip this. |
| AP-3  | Two parallel tenant policing systems                                  | HIGH     | Divergent semantics (see §3.5). |
| GA-1  | Empty `evaluation_results` → DENY (Phase 0 fix, now in force)          | RESOLVED | Phase 0 Cluster F closed this. Documented here as the constitutional precedent for AP-1's eventual flip. |

### 5.5 OBSERVABILITY RISK

| ID     | Site                                                                  | Severity | Description |
|--------|-----------------------------------------------------------------------|----------|-------------|
| OBS-1  | `observability/governance_metrics.py:33`, `governance_logging.py:34`   | LOW      | Only governance emits tenant_id to observability. Other substrates' metrics/logs are tenant-blind. Forensic dashboards cannot answer "what is tenant X's coordination throughput?". |

---

## 6. The constitutional propagation doctrine (forward intent)

This is **doctrine**, not implementation. Wedge B2+ binds against it.

### 6.1 The authority root (ratified by Wedge A)

The substrate's authority anchor is the tuple:

```
(environment_id, tenant_id, principal_id)
```

* `environment_id` is a peer of `tenant_id`, not a deployment-time-only
  concern.
* `principal_id` is the human / agent / service-account anchor below
  tenant.
* `organization_id` is a peer of `tenant_id` for hierarchy navigation,
  not authority routing.

### 6.2 The propagation contract

For every operation flowing through the substrate:

1. **Ingress MUST be typed.** The HTTP edge MUST construct typed
   `TenantId`, `PrincipalId`, `EnvironmentId` from auth claims before
   any substrate is touched. Today: not implemented. Wedge B5 / future
   wedges.
2. **The first substrate that receives the request MUST stamp the
   apex value object with the authority root.** Session does this
   correctly (`SessionIdentity.tenant_id`). Boundary does this
   partially (via `BoundarySource`). Agents does not (no trace field).
3. **Every downstream read of `tenant_id` MUST read from the apex
   value object's authority anchor, NOT from request/context shadow
   copies.** Session is the model; coordination is the
   anti-pattern.
4. **No substrate may merge authority from multiple sources without
   emitting a trace event identifying the resolution.** Supervisor's
   two-source coalescing and coordination's `or`-coalescing both
   violate this. Closure requires either single-source authority or
   an explicit `tenant_resolution_trace` event.
5. **Persistence MUST store the authority root verbatim.** Every
   record stores tenant_id — but as `str | None`. The future contract
   is that tenant_id is either `TenantId` (non-null) or the record is
   explicitly marked `tenant_scope=GLOBAL`.
6. **Deterministic identity derivation MUST NOT use `tenant_id or
   ''`.** Tenantless and tenant_id="" are constitutionally distinct
   authorities. The seed projection must be unambiguous (e.g. encode
   `None` as a sentinel like `"\x00"`, not as `""`).
7. **Tenant policing MUST have a single doctrine.** Either
   `governance.TenantScopePolicy` is the authority and coordination
   defers to it, or coordination owns network-tier tenant policing
   and governance owns content-tier tenant policing — with the
   division written down. Today: two parallel systems with opposite
   defaults.
8. **The resolver MUST be public, single, and substrate-shared.**
   `_tenant_id_for` is the right doctrine in the wrong location. It
   should move to `app/identity/resolution.py` as
   `resolve_tenant_id(*, subject, context)` and be the only resolver
   any substrate calls.

### 6.3 What must NOT propagate

* tenant_id MUST NOT propagate through opaque metadata dicts (DR-2).
* tenant_id MUST NOT be silently coalesced from multiple sources
  (DR-3, DR-4).
* tenant_id MUST NOT collapse `None` and `""` into the same
  derivation (CO-1, CO-2).
* tenant_id MUST NOT default to ALLOW when policy configuration is
  absent (AP-1 — flip required for production).

---

## 7. Wedge B+ roadmap (advisory — no code in this wedge)

This audit identifies eight remediation wedges, each constitutionally
independent. The order is the order of decreasing risk × decreasing
blast-radius:

| Wedge | Title                                              | Closes                | Risk if skipped                          |
|-------|----------------------------------------------------|-----------------------|------------------------------------------|
| B2    | Type ingress at boundary contracts only            | DR-1 (partial), OB-1 (partial) | Production ingress lands without typed tenants. |
| B3    | Add `tenant_id: TenantId | None` field to `AgentExecutionTrace` + remove metadata fishing in agents/persistence + supervisor/view_builder | DR-2, TR-2 | Agent authority remains opaque, replay fragile. |
| B4    | Replace `tenant_id or ''` with unambiguous projection in `boundary/identity.py`, `session/identity/__init__.py`, `organizational_intelligence/identity/__init__.py` | CO-1, CO-2, CO-3 | Two authority states collapse to one identifier. |
| B5    | Move `_tenant_id_for` to `app/identity/resolution.py` as public `resolve_tenant_id` + adopt across substrates | RH-1 | Resolution drift remains. |
| B6    | Emit `tenant_resolution_trace` event whenever two-source coalescing occurs (supervisor, coordination) | DR-3, DR-4 | Forensic queries cannot reconstruct authority source. |
| B7    | Unify or formally separate `TenantScopePolicy` ↔ `TenantIsolationEvaluator` doctrine | AP-3 | Two policing systems drift further. |
| B8    | Add HTTP-edge tenant extraction middleware (production blocker) | DR-1 (full) | No production ingress is safe. |
| B9    | Flip `TenantScopePolicy.open_allowlist` from ALLOW to DENY (post-config-rollout) | AP-1 | Permissive default reaches production. |

Each wedge is a **single commit**. Each wedge requires user
confirmation before execution per the Phase 1 freeze discipline.

---

## 8. What this audit does NOT do

* Does not introduce any code change.
* Does not mutate any serializer.
* Does not modify any governance policy.
* Does not modify any persistence record.
* Does not lift the Wedge A leaf invariant on `app/identity/`.
* Does not declare any of the eight remediation wedges authorised.
* Does not address `principal_id`, `organization_id`, or
  `environment_id` propagation. Those are sibling audits to be done
  before their respective Wedge B counterparts.

---

## 9. Validation

This document was produced under freeze discipline. Verification:

```
git diff --stat docs/identity/tenant-propagation-audit.md
# Only this file is new. No code paths touched.

cd apps/backend && ./venv/bin/pytest -q
# 1120 passed (unchanged from d28e03c).
```

Read-only audit complete. Wedge B1 sealed. Awaiting user direction
for Wedge B2 or higher.
