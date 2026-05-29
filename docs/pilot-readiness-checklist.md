# Operious AI - Pilot Readiness Checklist

# Anker Innovations 60-Day Pilot

## Instructions

Run each verification command. Mark PASS, FAIL, or NOT_MET. This
checklist must be fully green before pilot Day 1.

## 1. Infrastructure Health

- [NOT_MET] Backend health:
  `curl https://operious-ai-imad.fly.dev/api/v1/health`
  Expected: `{"status":"ok"}`. Not verified in this local PR_RT10 pass.
- [NOT_MET] All worker processes running:
  `fly status --app operious-ai-imad`
  Expected: `web`, `worker_diagnostic`, `worker_supervisor`,
  `worker_sop`, and `worker_maintenance` all running. Not verified in
  this local PR_RT10 pass.
- [NOT_MET] Database head:
  `fly ssh console --app operious-ai-imad`, then `alembic current`.
  Expected: `0052_boundary_ingress_language`. Not verified in production
  from this local PR_RT10 pass.

## 2. Test Gates

- [PASS] Backend test suite: PR_RT10 local gate showed 2,663 passing,
  3 skipped, and 0 failures.
- [PASS] Load tests: PR_RT10 local load gate showed 10/10 passing,
  including voice concurrent-call and overload admission tests.
- [PASS] Smoke tests: PR_RT10 local DB-enabled smoke gate showed 4/4
  passing.
- [PASS] Pyright: PR_RT10 local gate showed 0 errors and 440 warnings.
- [PASS] Frontend build: `npm run build` completed with 0 TypeScript
  errors. Existing Auth0/webpack warnings remain because local build
  lacks production Auth0 secrets.

## 3. Demo Tenant

- [NOT_MET] Five Anker sessions present:
  `venv/bin/python apps/backend/scripts/anker_demo/seed_anker_demo.py --verify-only`
  Expected: demo health ready and all five sessions present. Not verified
  in this PR_RT10 pass.
- [NOT_MET] DLQ empty:
  `GET /api/v1/operations/dead-letters` with operator token.
  Expected: `total=0`. Not verified against production.

## 4. Governance Policies

- [NOT_MET] Anker pilot governance policies loaded for action tools:
  `warranty_claim`, `replacement_order`, `refund_request`, and
  `warehouse_repair` configured in `anker-pilot`.
- [NOT_MET] Governance health: no policy chain returns unexpected DENY
  on pilot test tickets. Needs production tenant policy verification.

## 5. Security

- [NOT_MET] `AUDIT_EXPORT_HMAC_SECRET` set in Fly secrets.
- [NOT_MET] Auth0 operator capability configured for
  `barajaimad@gmail.com`.
- [NOT_MET] FORCE RLS active confirmed by Fly SSH database query.
- [NOT_MET] All secrets are in Fly secrets and not committed to code.

## 6. Command Center

- [NOT_MET] App accessible at `https://app.operious.com`.
- [NOT_MET] Operations Queue shows Anker sessions.
- [NOT_MET] Trace Inspector shows citations for sessions.
- [NOT_MET] Manager Approval inbox accessible.

## 7. Channels

- [NOT_MET] Email ingress endpoint active.
- [NOT_MET] WhatsApp ingress endpoint active.
- [NOT_MET] Webhook signature validation returns 401 on invalid
  signature in production.

## 8. Capacity

- [PASS] Voice capacity limit configured:
  `VOICE_CAPACITY_LIMIT=100` by default in backend configuration.
- [PASS] Worker diagnostic concurrency configured:
  `worker_diagnostic` runs Celery with `--concurrency=4` in
  `apps/backend/fly.toml`.
- [PASS] Admission thresholds configured:
  `ADMISSION_QUEUE_DEPTH_WARN=500` and
  `ADMISSION_QUEUE_DEPTH_REJECT=2000`.

## 9. Multilingual

- [NOT_MET] Arabic detection production check:
  POST a test ticket in Arabic.
  Expected: `source_language="ar"` in response metadata. Local RT9 tests
  cover this path; production check remains open.

## 10. Pilot Contact

- [PASS] Jiao Ma email drafted:
  `docs/outreach/jiao-ma-intro.md`.
- [NOT_MET] Pilot proposal ready.
- [PASS] Command Center demo walkthrough prepared:
  `apps/backend/scripts/anker_demo/demo_walkthrough.md`.

---

Signed off by: Imad Baraja

Date: 2026-05-29

All items: NOT_MET until production infrastructure, security, channel,
and business-readiness checks are verified.
