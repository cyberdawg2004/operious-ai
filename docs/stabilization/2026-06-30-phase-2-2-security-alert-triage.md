# Phase 2.2 Stabilized Security Alert Triage

Date: 2026-06-30
Branch: `phase-2-2-stabilized`
Repository: `cyberdawg2004/operious-ai`

This note records the per-alert disposition for the requested CodeQL and Dependabot backlog. It documents false-positive dismissals with evidence and captures the fixes/bump decisions applied in this branch.

## Tier 1

### #10 Clear-text logging of sensitive info

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: [scripts/rotate_secret.py](/home/imad-baraja/Projects/operious-ai/scripts/rotate_secret.py:257) only prints secret inventory names and operator instructions, including the literal placeholder `SECRET_NAME` at [scripts/rotate_secret.py](/home/imad-baraja/Projects/operious-ai/scripts/rotate_secret.py:269). It does not interpolate or print any live secret value.
- Reason: no secret material reaches logs; only static documentation text and secret identifiers are emitted.

### #13 Weak crypto hash in production helper

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: [apps/backend/app/core/twilio_signature.py](/home/imad-baraja/Projects/operious-ai/apps/backend/app/core/twilio_signature.py:15) is a dedicated Twilio signature helper, and its docstring states it returns Twilio's base64 HMAC-SHA1 signature. The helper is used by production webhook verification in [apps/backend/app/boundary/adapters/channel_webhooks.py](/home/imad-baraja/Projects/operious-ai/apps/backend/app/boundary/adapters/channel_webhooks.py:198) and [apps/backend/app/services/ticket_ingress_service.py](/home/imad-baraja/Projects/operious-ai/apps/backend/app/services/ticket_ingress_service.py:1900), plus the voice gate in [apps/backend/app/api/v1/routers/voice.py](/home/imad-baraja/Projects/operious-ai/apps/backend/app/api/v1/routers/voice.py:81).
- Reason: SHA-1 is not used as a general-purpose integrity primitive here; it is the provider-mandated HMAC algorithm for validating Twilio `X-Twilio-Signature` requests. Replacing it would break protocol compatibility rather than improve security.

## Tier 2

### #11 Weak crypto in `test_voice_provider_signature`

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: [apps/backend/tests/test_voice_provider_signature.py](/home/imad-baraja/Projects/operious-ai/apps/backend/tests/test_voice_provider_signature.py:286) defines a private `_twilio_signature()` test helper used only to generate expected Twilio-compatible fixtures for handshake tests.
- Reason: test-only fixture code; no production crypto behavior is introduced or shipped from this file.

### #12 Weak crypto in `test_voice_capacity`

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: [apps/backend/tests/load/test_voice_capacity.py](/home/imad-baraja/Projects/operious-ai/apps/backend/tests/load/test_voice_capacity.py:48) synthesizes a signed handshake for a load test, and the HMAC-SHA1 call is inside that fixture path at [apps/backend/tests/load/test_voice_capacity.py](/home/imad-baraja/Projects/operious-ai/apps/backend/tests/load/test_voice_capacity.py:59).
- Reason: load-test-only fixture code; it mirrors Twilio's required test signature format and is not production crypto.

### #6 Incomplete URL substring sanitization in `test_voice_provider_signature_url`

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: [apps/backend/tests/test_voice_provider_signature_url.py](/home/imad-baraja/Projects/operious-ai/apps/backend/tests/test_voice_provider_signature_url.py:21) is a spec/assertion file that checks server-derived canonical URL behavior using forged test URLs such as `"https://evil/x"` at lines 25, 34, 45, and 47.
- Reason: test assertion/spec fixture only; no production URL sanitizer or trust decision is implemented in this file.

### #7 Incomplete URL substring sanitization in `test_voice_provider_signature_url`

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: same file and rationale as #6.
- Reason: test assertion/spec fixture only; no production URL sanitizer or trust decision is implemented in this file.

### #8 Incomplete URL substring sanitization in `test_channel_webhook_signature_url`

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: [apps/backend/tests/test_channel_webhook_signature_url.py](/home/imad-baraja/Projects/operious-ai/apps/backend/tests/test_channel_webhook_signature_url.py:30) is a spec/assertion file that feeds forged URLs such as `"https://evil.test/forged"` into tests at lines 36, 47, 62, and 64 to verify fail-closed behavior.
- Reason: test assertion/spec fixture only; no production URL sanitizer or trust decision is implemented in this file.

### #9 Incomplete URL substring sanitization in `test_channel_webhook_signature_url`

- Disposition: dismissed with reason.
- Verdict: false positive.
- Evidence: same file and rationale as #8.
- Reason: test assertion/spec fixture only; no production URL sanitizer or trust decision is implemented in this file.

## Tier 3

### #1-#5 Workflow does not contain permissions

- Disposition: fixed.
- Verdict: genuine hardening issue.
- Evidence: [ci.yml](/home/imad-baraja/Projects/operious-ai/.github/workflows/ci.yml:9) and [deploy.yml](/home/imad-baraja/Projects/operious-ai/.github/workflows/deploy.yml:13) now declare explicit least-privilege workflow permissions.
- Fix:
  - CI workflow now defaults to `contents: read`.
  - Deploy workflow now defaults to `contents: read`.
  - Deploy `gate` job keeps its narrower job-level override for `actions: read` plus `contents: read`.
- Reason: removes implicit broad token permissions from CI/deploy workflows without changing job behavior.

## Tier 4

### LangGraph dependency alerts

#### #107, #109, #111 `langgraph-checkpoint` unsafe deserialization

- Disposition: bumped.
- Verdict: package version was genuinely below the fixed version, but current repo exposure appears low.
- Evidence:
  - `apps/command-center2/requirements.txt` and `apps/marketing2/requirements.txt` previously pinned `langgraph-checkpoint==4.1.0`, while the GitHub advisory for `GHSA-fjqc-hq36-qh5p` fixes the issue in `4.1.1`.
  - Static search found no `langgraph` imports or checkpoint-loading code under `apps/command-center2` or `apps/marketing2`; only pinned requirements and roadmap mentions were present.
- Action: bumped both app requirements files to `langgraph-checkpoint==4.1.1`.
- Reason: low observed reachability today, but the pinned version was still vulnerable and the minimal bump is low risk.

#### #108, #110, #112 `langgraph-sdk` unsafe URL path construction

- Disposition: bumped.
- Verdict: package version was genuinely below the fixed version, but current repo exposure appears low.
- Evidence:
  - `apps/command-center2/requirements.txt` and `apps/marketing2/requirements.txt` previously pinned `langgraph-sdk==0.3.14`, while the GitHub advisory for `GHSA-w39p-vh2g-g8g5` fixes the issue in `0.3.15`.
  - Static search found no `langgraph_sdk` imports or SDK call sites under `apps/command-center2` or `apps/marketing2`.
- Action: bumped both app requirements files to `langgraph-sdk==0.3.15`.
- Reason: low observed reachability today, but the pinned version was still below the fixed version and the minimal bump is low risk.

#### Follow-up note for later cleanup

- Static search found the `langgraph*` packages pinned in `apps/command-center2` and `apps/marketing2`, but no current import or call sites in those app trees.
- This makes `langgraph`, `langgraph-checkpoint`, `langgraph-prebuilt`, and `langgraph-sdk` candidates for future dependency-removal work rather than perpetual version-bump maintenance.
- Not acted on in this pass because the requested scope was alert triage reconciliation, not dependency removal.

### JS-YAML development-scope alerts

#### #113

- Disposition: bumped.
- Verdict: genuine vulnerable dev-only lockfile entry, low operational risk.
- Evidence: root [package-lock.json](/home/imad-baraja/Projects/operious-ai/package-lock.json:6576) resolved `js-yaml` to `4.1.1`, while `GHSA-h67p-54hq-rp68` fixes the quadratic-complexity DoS in `4.2.0`. The dependency is dev-only via `@eslint/eslintrc` at [package-lock.json](/home/imad-baraja/Projects/operious-ai/package-lock.json:1246).
- Action: bumped root lockfile resolution to `js-yaml@4.2.0`.

#### #114

- Disposition: bumped.
- Verdict: genuine vulnerable dev-only lockfile entry, low operational risk.
- Evidence: [apps/command-center2/frontend/package-lock.json](/home/imad-baraja/Projects/operious-ai/apps/command-center2/frontend/package-lock.json:4562) resolved `js-yaml` to `4.1.1`, dev-only via `@eslint/eslintrc` at line 428.
- Action: bumped lockfile resolution to `js-yaml@4.2.0`.

#### #115

- Disposition: bumped.
- Verdict: genuine vulnerable dev-only lockfile entry, low operational risk.
- Evidence: [apps/marketing2/frontend/package-lock.json](/home/imad-baraja/Projects/operious-ai/apps/marketing2/frontend/package-lock.json:4959) resolved `js-yaml` to `4.1.1`, dev-only via `@eslint/eslintrc` at line 427.
- Action: bumped lockfile resolution to `js-yaml@4.2.0`.

#### #116

- Disposition: bumped.
- Verdict: genuine vulnerable dev-only lockfile entry, low operational risk.
- Evidence: [apps/marketing2/frontend/pnpm-lock.yaml](/home/imad-baraja/Projects/operious-ai/apps/marketing2/frontend/pnpm-lock.yaml:1442) resolved `js-yaml` to `4.1.1`.
- Action: bumped lockfile resolution to `js-yaml@4.2.0`.

## Operational note

- GitHub alert-state writeback was not performed from this workspace because `gh auth status` reports the configured GitHub token is invalid. The dispositions above are the documented reasons to use if/when the alerts are dismissed in GitHub.
