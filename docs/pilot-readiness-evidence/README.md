# S-10 Pilot Readiness Evidence

This directory archives the dated live-production evidence for S-10:
production readiness verification. S-10 closes only when the deployed
environment, not just local tests, proves the core controls are active.

Capture date: 2026-06-06

Capture target (all proofs captured against this build):

- Fly app: `operious-ai-imad`
- Fly hostname: `https://operious-ai-imad.fly.dev`
- Fly release: `v125`
- Fly image: `operious-ai-imad:deployment-01KTEZ2QESEC8AK3PWQ686GZ5E`
- Fly machine: `6e8207e3b215e8` (region `sin`)
- Git commit: `3a3d7fc`
- Branch: `phase-2-2-stabilized`

Use `capture-populate-runbook.md` for the exact commands used to capture and
populate the proof files.

## Status: CAPTURED

Every S-10 proof requirement below was captured live against the deployed
build above. Each dated proof file has `capture_status: "captured"` with the
raw probe output in its `evidence` block, and `manifest.json` is `captured`.

- **Direct spoofed authority-header rejection** — forged `X-Tenant-ID` rejected
  with `401 unauthorized` (production-coarsened).
- **Bearer/Auth0 success with verified namespaced tenant claims** — `/auth/me`
  `200`, `authority_source: verified`, `tenant_id: anker-pilot`, operator
  capability bundle present.
- **Production-role RLS tenant isolation** — six sensitive tenant tables, each
  with real control rows under `anker-pilot` and **zero** cross-tenant
  visibility under the `operious_app` role.
- **Worker + DLQ proof** — a labeled deliberate-failure task was consumed by the
  live worker, dead-lettered, and the DLQ row read back.
- **Production secrets/provider/readiness output** — `check_production_readiness`
  returned `READY` (exit 0) in-container.
- **Live workflow proof** — clean `PASS smoke`: a routine charging ticket
  auto-resolved end-to-end (`diagnostic_analysis_completed` →
  `resolution_proposal_created` → `resolution_outbound_draft_created`), grounded
  on the decrypted Anker Charging Issue Policy SOP via real OpenAI retrieval and
  real Anthropic reasoning.
- **Rollback evidence** — documented rollback path (Fly release-history targets
  v122–v125 + `fly-deploy-rollback.md`; Neon continuous PITR +
  `neon-migration-rollback.md`). A live rollback drill was intentionally NOT run
  against production to avoid disrupting the pilot.

## Bugs and gaps surfaced and fixed during live verification

- Rate-limit TTL could be missing after Redis counter creation — fixed with the
  atomic INCR/TTL/EXPIRE script (`de96355`).
- Semantic-validation drift could be downgraded to a retryable persistence
  failure — fixed by preserving terminal `SEMANTIC_REJECTION` (`6be1522`).
- Successful completion could retain stale failure fields — fixed by clearing
  `failed_at`/`error` on completion (`04d201e`).
- The diagnostic worker grounded the agent on **ciphertext** SOPs — fixed by
  supplying data-protection to the worker knowledge repository so live RAG
  decrypts SOPs (`80c35fb`).
- Standard remediations (`credit`, `rma`) absent from the cited SOP were flagged
  as ungrounded governance drift and dead-lettered — fixed by an authorized
  remediation allowlist (`2a691e9`), bounded semantic self-correction
  (`e92e886`), and escalate-instead-of-dead-letter for terminal diagnostic
  blocks (`3a3d7fc`).
- The live smoke ticket literally contained the word "smoke", which correctly
  tripped the safety-hazard policy and routed to escalation — fixed by using a
  routine charging ticket with no safety-trigger words (`1bec137`).

## Tracked items (not blockers)

- Upstash latency can stretch live smoke timing; the smoke probe is retry- and
  timeout-aware.
- Tighten the IPv4 portion of production `TRUSTED_PROXIES` from `172.16.0.0/12`
  to the exact Fly peer range once documented.

## Evidence Files

| File | Requirement | Contents |
| --- | --- | --- |
| `2026-06-06-spoofing-pass.json` | Direct spoof rejection | Live `401`/unauthorized for forged authority headers. |
| `2026-06-06-rls-pass.json` | Production-role RLS | Six per-table live RLS runs, zero cross-tenant visibility. |
| `2026-06-06-workers-dlq-pass.json` | Workers + DLQ | Labeled deliberate-failure task, DLQ row, read-back proof. |
| `2026-06-06-bearer-auth0-verified-claims.json` | Bearer/Auth0 | `/api/v1/auth/me` verified tenant + capability claims. |
| `2026-06-06-live-workflow-recovered-smoke.json` | Live workflow | Clean `PASS smoke`: end-to-end auto-resolution with grounded resolution draft. |
| `2026-06-06-readiness-ready.json` | Readiness | In-container `check_production_readiness` → READY. |
| `2026-06-06-rollback-reference.json` | Rollback | Fly release-history targets + Neon PITR + runbook links. |
| `manifest.json` | Bundle index | Machine-readable proof index + fixes + tracked items. |
| `capture-populate-runbook.md` | Operator runbook | Exact capture/populate/finalize commands. |

## Integrity rule

Evidence blocks contain raw probe output only. Failed or timed-out runs are
never rewritten into a fake green; if a probe fails, its real output is recorded
and the gap is fixed before re-capture.
