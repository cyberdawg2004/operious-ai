# S-10 Pilot Readiness Evidence

This directory archives the dated live-production evidence for S-10:
production readiness verification. S-10 closes only when the deployed
environment, not just local tests, proves the core controls are active.

Capture date: 2026-06-06

Default capture target:

- Fly app: `operious-ai-imad`
- Fly hostname: `https://operious-ai-imad.fly.dev`
- Fly release/image: `deployment-01KTDGTXM7DKQ06Z6JBGA9CYPD`
- Fly image: `operious-ai-imad:deployment-01KTDGTXM7DKQ06Z6JBGA9CYPD`
- Fly machine version: `122`
- Git commit: `edc1a2c5f1cb60ccd71097e00d20d813ef4e3b5f`
- Branch: `phase-2-2-stabilized`

If an individual proof was captured against a different Fly release or git
commit, update that proof file's `captured_against` block before treating the
bundle as final.

## Honest Summary

The 2026-06-06 live session produced proof for every S-10 requirement. This
bundle preserves those proofs as dated files:

- Direct spoofed authority-header rejection.
- Bearer/Auth0 success with verified namespaced tenant claims.
- Production-role RLS tenant isolation across six sensitive tenant tables.
- Worker and DLQ smoke/replay proof.
- Production secrets/provider/readiness output.
- Rollback evidence through a Neon snapshot reference and the migration
  rollback runbook.
- Live workflow proof from recovered traces: real OpenAI retrieval, decrypted
  Anker SOP grounding, real Anthropic usage, and persisted execution IDs.

The live verification work surfaced and fixed three production bugs before
this archive was created:

- Rate-limit TTL could be missing after Redis counter creation; fixed by the
  atomic INCR/TTL/EXPIRE script in `de96355`.
- Semantic validation drift could be downgraded to retryable persistence
  failure; fixed by preserving terminal `SEMANTIC_REJECTION` in `6be1522`.
- Successful completion could retain stale failure fields; fixed by clearing
  `failed_at` and `error` on completion in `04d201e`.

Two pilot items remain tracked rather than hidden:

- Upstash latency can stretch live smoke timing.
- Semantic-validation calibration can reject borderline LLM wording. That is
  correct governance behavior, but the calibration should be tuned for fewer
  unnecessary retries or escalations.

One hardening item remains tracked:

- Tighten the IPv4 portion of production `TRUSTED_PROXIES`. The current
  `172.16.0.0/12` value fixed legitimate Fly proxy ingress, but is broader
  than the exact Fly IPv4 peer range proven by documentation.

## Evidence Files

| File | Requirement | Contents |
| --- | --- | --- |
| `2026-06-06-spoofing-pass.json` | Direct spoof rejection | Coarsened 401/unauthorized proof for spoofed authority headers. |
| `2026-06-06-rls-pass.json` | Production-role RLS | Six per-table live RLS runs with zero cross-tenant visibility. |
| `2026-06-06-workers-dlq-pass.json` | Workers + DLQ | Labeled deliberate-failure task, DLQ row, and read-back proof. |
| `2026-06-06-bearer-auth0-verified-claims.json` | Bearer/Auth0 | `/api/v1/auth/me` verified tenant and capability claims. |
| `2026-06-06-live-workflow-recovered-smoke.json` | Live workflow | Recovered trace proving real Anthropic usage and decrypted Charging SOP grounding. |
| `2026-06-06-readiness-ready.json` | Readiness | Module-form production readiness command output. |
| `2026-06-06-rollback-reference.json` | Rollback | Neon snapshot reference and rollback runbook link. |
| `manifest.json` | Bundle index | Machine-readable list of the proof files and tracked residuals. |

## Population Rule

Paste raw JSON or command output into the relevant file's `evidence` block
before final signoff. Do not rewrite failed or timeout evidence into a fake
green. For the live workflow proof, this archive intentionally records
recovered trace evidence instead of a forced `PASS smoke` line, because the
live smoke probe timed out under real Upstash latency and intermittent
semantic rejection. The trace is the proof: execution IDs, nonzero Anthropic
tokens, and a decrypted Charging Issue Policy citation with score.
