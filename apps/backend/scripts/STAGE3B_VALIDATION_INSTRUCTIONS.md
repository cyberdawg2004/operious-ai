# Stage 3b Live Validation Instructions

## What This Proves

This script validates Stage 3b on **deployed prod** (operious-ai-imad.fly.dev at commit `baa0e31`):

1. **LIVE READ**: Prod egress reaches httpbin.org via `?probe_http=true` — returns `status:200`
2. **GOVERNED ROUND-TRIP**: Money-act queues as pending → Imad approves → POST fires ONLY THEN
3. **FAIL-CLOSED**: Undeclared commitment_kind → human approval required (POST never auto-fires)

## Prerequisites

1. **Auth0 Token**: Get your token from browser dev tools
   - Open https://operious-ai-imad.fly.dev in browser
   - Open Dev Tools (F12) → Network tab
   - Refresh page or make any API call
   - Find a request with `Authorization: Bearer ...` header
   - Copy the full token (everything after `Bearer `)

2. **Fresh Webhook.site URL**: 
   - Visit https://webhook.site/
   - Copy your unique URL (e.g., `https://webhook.site/abc123-def456-...`)
   - Keep this tab open — you'll check it during validation

3. **Python Environment**: 
   - Must have `httpx` installed: `pip install httpx`
   - Run from the backend directory

## How to Run

```bash
# Set your token as an environment variable (NEVER commit this!)
export OPERIOUS_TOKEN="eyJ0eXAiOiJKV1QiLCJhbGc..."  # Your full token here

# Run the validation script
cd apps/backend
python scripts/validate_stage3b_live.py --webhook-url "https://webhook.site/YOUR-UUID-HERE"
```

## What You'll See

### Step 1: LIVE READ FROM PROD
- Script creates/verifies `httpbin.read` connector config
- Calls `/tenant/anker-pilot/connectors/httpbin.read/test?probe_http=true`
- **Evidence**: `http_probe: "status:200"` → proves prod egress reached httpbin.org live

### Step 2: SET UP WEBHOOK.ACT + APPROVAL-GATED POLICY
- Script creates `webhook.act` connector config pointing to your webhook.site URL
- Verifies action_tools policy is approval-gated for money operations
- **Evidence**: Policy shown, gating confirmed

### Step 3-5: GOVERNED ROUND-TRIP (MANUAL)
⚠️ **This requires agent orchestration** (cannot be fully automated in this script)

The script will pause and print instructions:

1. **Before triggering**: Confirm webhook.site shows **NO requests** yet (empty)
2. **Trigger action**: Use an internal tool/test harness to trigger a money-act using `webhook.act`
3. **Verify queue**: Action should queue as `pending_human_approval` (check logs/DB)
4. **Enter approval ID**: Script prompts for the approval ID
5. **Confirm empty**: Script asks you to confirm webhook.site is STILL empty
6. **Approve**: Script calls `/action-approvals/{id}/approve` as you
7. **Verify POST**: Script asks you to confirm POST now appears on webhook.site

**Evidence**: 
- Empty BEFORE approval → proves POST didn't auto-fire
- POST appears AFTER approval → proves approval was the gate
- Timestamp on webhook.site should be after approval timestamp

### Step 6: FAIL-CLOSED
- Script confirms fail-closed behavior via test suite + code inspection
- **Evidence**: `test_governance_gate_blocks_undeclared_commitment_kind` test passes
- Code reference: `action_governance.py:172` — `if commitment_kind is None: REQUIRE_APPROVAL`

## Expected Output

```
🚀 Stage 3b Live Validation
   Tenant: anker-pilot
   API: https://operious-ai-imad.fly.dev/api/v1
   Webhook: https://webhook.site/...
   Token: ***REDACTED*** (1234 chars)

================================================================================
  STEP 1: LIVE READ FROM PROD
================================================================================
[12:34:56] INFO: Checking connector config for httpbin.read...
[12:34:56] INFO: ✓ Connector config httpbin.read already exists
[12:34:56] INFO: Testing httpbin.read with probe_http=true...
[12:34:56] INFO: POST /tenant/anker-pilot/connectors/httpbin.read/test -> 200
[12:34:56] INFO: ✓ PASS: HTTP probe returned status:200
[12:34:56] INFO: ✓ PROOF: Prod egress reached httpbin.org, got HTTP 200

================================================================================
  STEP 2: SET UP WEBHOOK.ACT + APPROVAL-GATED POLICY
================================================================================
[12:34:57] INFO: Checking connector config for webhook.act...
[12:34:57] INFO: Creating connector config webhook.act via change request...
[12:34:57] INFO: ✓ Change request approved and applied
[12:34:58] INFO: Checking action_tools policy...
[12:34:58] INFO: ✓ Policy appears approval-gated (refund.request rule found)

================================================================================
  STEP 3: TRIGGER MONEY-ACT (MANUAL)
================================================================================
[12:34:59] WARN: ⚠ ACTION REQUIRED: This script cannot trigger actions directly.
   The connector invocation requires the full agent orchestration pipeline.
   
To complete the round-trip test:
  1. The webhook.act connector is configured
  2. Open webhook.site tab: https://webhook.site/...
  3. Verify webhook.site shows NO requests yet (empty)
  4. Trigger a test action that uses the connector
  5. Action should queue as pending_human_approval
  6. Note the approval ID from logs/database

Enter approval ID (or press Enter to skip round-trip test): 
```

## Security Notes

- ✅ Token is NEVER printed or logged
- ✅ Token is passed via env var (not command line args visible in ps)
- ✅ Script redacts token from all output
- ✅ Webhook.site URL is ephemeral test data (no secrets)

## Troubleshooting

**"401 Unauthorized"**: Token expired or invalid — get a fresh one from browser dev tools

**"Change request requires approval"**: The script will print the CR ID — approve it manually, then press Enter

**"No action_tools policy found"**: Script continues with fail-closed default (money → human approval)

**Round-trip test skipped**: Triggering requires agent orchestration — use internal test harness separately

## Next Steps After Validation

1. **Confirm all PASS**: Live read, policy check, fail-closed all show ✓
2. **Manual round-trip**: If you triggered an action, confirm empty→approve→POST sequence
3. **Targeted harness**: Run existing warranty tests to confirm unchanged behavior:
   ```bash
   pytest apps/backend/tests/test_warranty_connector.py -xvs
   ```

## Evidence for Stage 3b Sign-Off

After successful run, you have:
- ✅ Live read: `http_probe: status:200` from deployed prod
- ✅ HTTP probe: Proves egress + SSRF + TLS working on baa0e31
- ✅ Connector config: `webhook.act` configured via dual-control
- ✅ Policy gating: Money ops require human approval (not auto-exec)
- ✅ Fail-closed: Test suite + code confirms undeclared → human
- ✅ Round-trip: Manual verification of queue→approve→POST sequence
