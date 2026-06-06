# S-10 Capture And Populate Runbook

Use this runbook to capture the live S-10 production proofs and populate the
dated evidence files in this directory.

Setup:

```bash
cd apps/backend
BASE=https://operious-ai-imad.fly.dev
read -rsp "OPERIOUS_API_TOKEN: " TOKEN; echo
```

Default deployed target for this bundle:

- Fly app: `operious-ai-imad`
- Git commit: `edc1a2c5f1cb60ccd71097e00d20d813ef4e3b5f`
- Fly release/image: `deployment-01KTDGTXM7DKQ06Z6JBGA9CYPD`

If production has been redeployed, update every `captured_against` block and
re-run readiness before finalizing the bundle.

## 1. Spoofing

Target file: `2026-06-06-spoofing-pass.json`

Run anywhere:

```bash
../../venv/bin/python -m scripts.s10_prep.live_verification_probes spoofing \
  --base-url "$BASE" --forged-tenant-id forged-tenant
```

Paste the `PASS spoofing {...}` JSON into the file's `evidence` block.

## 2. Bearer/Auth0 Verified Claims

Target file: `2026-06-06-bearer-auth0-verified-claims.json`

```bash
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/auth/me"
```

Paste the returned verified tenant/capability JSON. Do not archive the token.

## 3. RLS Tenant Isolation

Target file: `2026-06-06-rls-pass.json`

Run on a Fly machine with `DATABASE_URL` available, or run locally with the
production Neon DSN set in `DATABASE_URL`.

```bash
for T in operational_sessions boundary_ingress coordination_envelopes \
         dead_letter_tasks governance_decisions tenant_knowledge_documents; do
  DATABASE_URL='<neon prod dsn>' ../../venv/bin/python -m scripts.s10_prep.live_verification_probes rls \
    --table "$T" --tenant-a anker-pilot --tenant-b '<a-second-real-tenant>'
done
```

Paste each `PASS rls {...}` object into the file's `evidence.runs` array.

## 4. Workers + DLQ

Target file: `2026-06-06-workers-dlq-pass.json`

Requires production DB access and the live worker fleet running.

```bash
DATABASE_URL='<neon prod dsn>' ../../venv/bin/python -m scripts.s10_prep.live_verification_probes workers-dlq \
  --tenant-id anker-pilot --probe-id "s10-dlq-proof-$(date +%Y%m%d-%H%M%S)"
```

Paste the `PASS workers_dlq {...}` JSON. A deliberate worker failure and
labeled DLQ row are expected proof artifacts, not a production incident.

## 5. Live Smoke

Target file: `2026-06-06-live-workflow-recovered-smoke.json`

```bash
../../venv/bin/python -m scripts.s10_prep.live_verification_probes smoke \
  --base-url "$BASE" --tenant-id anker-pilot --bearer-token "$TOKEN"
```

If this emits `PASS smoke {...}`, paste it directly. If it times out under
Upstash latency or hits intermittent semantic rejection, capture the recovered
trace instead. Do not fake a green. The recovered trace should include:

- Session, ingress, dispatch, execution, and governance decision IDs.
- Anthropic usage row with provider, model, and nonzero prompt/completion
  tokens.
- Decrypted Charging Issue Policy citation and score.
- A note explaining why the probe did not emit a clean pass.

## 6. Production Readiness

Target file: `2026-06-06-readiness-ready.json`

Must run where production secrets are present:

```bash
fly ssh console -a operious-ai-imad -C "python -m scripts.check_production_readiness"
```

Expected output:

```text
production readiness: READY
```

Paste stdout and exit code.

## 7. Rollback

Target file: `2026-06-06-rollback-reference.json`

Paste the Neon snapshot or restore-point identifier and timestamp. Keep the
rollback runbook link:

```text
../runbooks/neon-migration-rollback.md
```

## Finalize

After all evidence is pasted:

1. Change each dated proof file's `capture_status` to `captured`.
2. Change `manifest.json` `capture_status` to `captured`.
3. Confirm each proof file has the git commit and Fly release it ran against.
4. Update `README.md` only if the populated evidence differs from this
   runbook's assumptions.
5. Validate the bundle:

   ```bash
   for f in docs/pilot-readiness-evidence/*.json; do
     python3 -m json.tool "$f" >/dev/null || exit 1
   done
   git diff --check
   ```

